/**
 * Apple Mail JXA Core Library
 *
 * Shared utilities for fast, batch-optimized Mail.app automation.
 * This library is injected into all JXA scripts to provide consistent
 * error handling, account/mailbox resolution, and batch fetching.
 */

const Mail = Application("Mail");

const MailCore = {
    /** Read one message's recipients with two batched property fetches. */
    getRecipients(message, property) {
        const recipients = message[property];
        const names = recipients.name();
        const addresses = recipients.address();
        return addresses.map((address, i) => ({
            name: names[i] || "",
            address: address || "",
        }));
    },

    /** Mail can silently substitute its default sender; fail before sending. */
    assertSenderAccount(message, account) {
        const sender = MailCore.senderAddress(message.sender());
        const aliases = account.emailAddresses().map(a => a.toLowerCase());
        if (aliases.indexOf(sender) === -1) {
            throw new Error("Mail.app selected a different sender; check account settings before retrying.");
        }
    },

    senderAddress(sender) {
        const match = sender.match(/<([^<>]+)>\s*$/);
        return (match ? match[1] : sender).trim().toLowerCase();
    },

    normalizeBody(body) {
        // Mail's MIME conversion adds enclosing blank lines and whitespace.
        return body.replace(/\r\n?/g, "\n")
            .replace(/[ \t]+\n/g, "\n")
            .replace(/^\n+/, "").replace(/\s+$/, "");
    },

    /** Mail 16 ignores JXA reply.content assignment. Use its native setter.
     * The script is constant: all caller data travels in typed descriptors,
     * never interpolated AppleScript source, command arguments, or a file.
     */
    setReplyBody(message, body, fallbackQuote) {
        ObjC.import("Foundation");
        const expected = body + "\n\n" + fallbackQuote;
        // Reading an uninitialized reply's rich text before setting it leaves
        // Mail 16 returning stale empty content. Reappend the source explicitly.
        const source = `on fillReply(outgoingId, expectedSubject, newContent)
    tell application "Mail"
        set replyMessage to outgoing message id outgoingId
        if subject of replyMessage is not expectedSubject then error "Reply identity changed"
        set content of replyMessage to newContent
        set visible of replyMessage to false
        return content of replyMessage as text
    end tell
end fillReply`;
        const script = $.NSAppleScript.alloc.initWithSource(source);
        // ascr/psbr invokes a local AppleScript handler; snam names it and
        // ---- contains its positional arguments. Use a real target descriptor
        // (a null target crashes the JXA Objective-C bridge on macOS 26).
        const event = $.NSAppleEventDescriptor
            .appleEventWithEventClassEventIDTargetDescriptorReturnIDTransactionID(
                0x61736372, 0x70736272,
                $.NSAppleEventDescriptor.currentProcessDescriptor, -1, 0
            );
        event.setParamDescriptorForKeyword(
            $.NSAppleEventDescriptor.descriptorWithString("fillreply"),
            0x736e616d
        );
        const args = $.NSAppleEventDescriptor.listDescriptor;
        args.insertDescriptorAtIndex(
            $.NSAppleEventDescriptor.descriptorWithInt32(message.id()), 1
        );
        [message.subject(), expected].forEach((value, i) => {
            args.insertDescriptorAtIndex(
                $.NSAppleEventDescriptor.descriptorWithString(value), i + 2
            );
        });
        event.setParamDescriptorForKeyword(args, 0x2d2d2d2d);
        const error = Ref();
        const result = script.executeAppleEventError(event, error);
        if (!result) {
            throw new Error("Mail.app could not set the reply body; nothing was sent. Check Drafts before retrying.");
        }
        const actual = ObjC.unwrap(result.stringValue);
        if (MailCore.normalizeBody(actual) !== MailCore.normalizeBody(expected)) {
            throw new Error("Mail.app did not apply the reply body; nothing was sent. Check Drafts before retrying.");
        }
    },

    /** Snapshot the scoped Drafts IDs before composing, never outgoing IDs. */
    snapshotDrafts(account) {
        try {
            const mailbox = MailCore.getMailbox(account, "Drafts");
            return {mailbox: mailbox, ids: mailbox.messages.id(), account: account.name()};
        } catch (_) {
            return null;
        }
    },

    /** Read back one new, matching saved draft. Ambiguity is not a handle. */
    findSavedDraft(snapshot, message, inReplyTo) {
        const unknown = {reference: null, threaded: "unconfirmed"};
        if (!snapshot) return unknown;
        try {
            const subject = message.subject();
            const body = message.content();
            const sender = MailCore.senderAddress(message.sender());
            const addresses = (msg, prop) => MailCore.getRecipients(msg, prop)
                .map(r => r.address.toLowerCase()).sort().join("\n");
            const props = ["toRecipients", "ccRecipients", "bccRecipients"];
            const expected = props.map(prop => addresses(message, prop));
            for (let attempt = 0; attempt < 10; attempt++) {
                const ids = snapshot.mailbox.messages.whose({subject: subject}).id()
                    .filter(id => snapshot.ids.indexOf(id) === -1);
                if (ids.length > 1) return unknown;
                if (ids.length === 1) {
                    const id = ids[0];
                    if (!Number.isInteger(id) || id <= 0) return unknown;
                    const saved = snapshot.mailbox.messages.byId(id);
                    if (MailCore.normalizeBody(saved.content()) !== MailCore.normalizeBody(body) ||
                        MailCore.senderAddress(saved.sender()) !== sender ||
                        props.some((prop, i) => addresses(saved, prop) !== expected[i])) {
                        return unknown;
                    }
                    const reference = {
                        account: snapshot.account,
                        mailbox: snapshot.mailbox.name(),
                        message_id: id,
                    };
                    let threaded = "unconfirmed";
                    if (inReplyTo) {
                        // Ignore body text; unfold only the MIME header block.
                        try {
                            const headers = saved.source().split(/\r?\n\r?\n/, 1)[0]
                                .replace(/\r?\n[ \t]+/g, " ");
                            const match = headers.match(/^In-Reply-To:\s*(.+)$/mi);
                            const parent = inReplyTo.replace(/^<|>$/g, "");
                            threaded = !!match && match[1].split(/\s+/)
                                .some(value => value.replace(/^<|>$/g, "") === parent);
                        } catch (_) {}
                    }
                    return {reference: reference, threaded: threaded};
                }
                if (attempt < 9) delay(0.2);
            }
        } catch (_) {
            // save() already happened. Never turn readback failure into a retry.
        }
        return unknown;
    },

    /**
     * Get an account by name, or the first account if name is null/empty.
     * @param {string|null} name - Account name or null for default
     * @returns {Account} Mail account object
     */
    getAccount(name) {
        if (name) {
            return Mail.accounts.byName(name);
        }
        const accounts = Mail.accounts();
        if (accounts.length === 0) {
            throw new Error("No mail accounts configured");
        }
        return accounts[0];
    },

    /**
     * Get a mailbox from an account.
     *
     * Tries an exact match first, then falls back to
     * case-insensitive matching and common aliases
     * (e.g. "Sent Messages" → "Sent Items").
     *
     * @param {Account} account - Mail account object
     * @param {string} name - Mailbox name (e.g., "INBOX", "Sent")
     * @returns {Mailbox} Mailbox object
     */
    getMailbox(account, name) {
        // Fast path: exact match
        try {
            const mb = account.mailboxes.byName(name);
            // Force evaluation to detect -1728 early
            mb.name();
            return mb;
        } catch (_) {
            // Fall through to fuzzy matching
        }

        // Alias groups: names that refer to the same logical
        // mailbox across different providers/locales
        const aliases = [
            ["INBOX", "Inbox"],
            [
                "Sent",
                "Sent Items",
                "Sent Messages",
                "Sent Mail",
            ],
            [
                "Trash",
                "Deleted Items",
                "Deleted Messages",
                "Bin",
            ],
            [
                "Drafts",
                "Draft",
            ],
            [
                "Junk",
                "Junk Email",
                "Spam",
            ],
            [
                "Archive",
                "All Mail",
            ],
        ];

        const lower = name.toLowerCase();
        const names = account.mailboxes.name();

        // Find which alias group the requested name belongs to
        let candidates = null;
        for (const group of aliases) {
            if (group.some((a) => a.toLowerCase() === lower)) {
                candidates = group;
                break;
            }
        }

        // Try alias group members first
        if (candidates) {
            for (const alt of candidates) {
                if (names.some((n) => n === alt)) {
                    return account.mailboxes.byName(alt);
                }
            }
        }

        // Last resort: case-insensitive match on actual names
        for (const actual of names) {
            if (actual.toLowerCase() === lower) {
                return account.mailboxes.byName(actual);
            }
        }

        // Nothing found — throw the standard error
        return account.mailboxes.byName(name);
    },

    /**
     * Batch fetch multiple properties from a messages collection.
     * This is THE critical optimization - one IPC call per property
     * instead of one per message.
     *
     * @param {Messages} msgs - Messages collection from a mailbox
     * @param {string[]} props - Property names to fetch
     * @returns {Object} Map of property name to array of values
     */
    batchFetch(msgs, props) {
        const result = {};
        for (const prop of props) {
            result[prop] = msgs[prop]();
        }
        return result;
    },

    /**
     * Get message IDs for referencing specific messages later.
     * @param {Messages} msgs - Messages collection
     * @returns {string[]} Array of message IDs
     */
    getMessageIds(msgs) {
        return msgs.id();
    },

    /**
     * Get a specific message by ID.
     * @param {string} messageId - The message ID
     * @returns {Message} Message object
     */
    getMessageById(messageId) {
        // Messages are referenced by ID across all accounts
        return Mail.messages.byId(messageId);
    },

    /**
     * Wrap an operation with error handling.
     * @param {Function} fn - Function to execute
     * @returns {Object} {ok: true, data: ...} or {ok: false, error: ...}
     */
    safely(fn) {
        try {
            return { ok: true, data: fn() };
        } catch (e) {
            return { ok: false, error: String(e) };
        }
    },

    /**
     * Get today's date at midnight for filtering.
     * @returns {Date} Today at 00:00:00
     */
    today() {
        const d = new Date();
        d.setHours(0, 0, 0, 0);
        return d;
    },

    /**
     * Get a date N days ago at midnight for filtering.
     * @param {number} days - Number of days ago
     * @returns {Date} Date at 00:00:00 N days ago
     */
    daysAgo(days) {
        const d = new Date();
        d.setDate(d.getDate() - days);
        d.setHours(0, 0, 0, 0);
        return d;
    },

    /**
     * Format a date for JSON output.
     * @param {Date} date - Date to format
     * @returns {string} ISO string or null if invalid
     */
    formatDate(date) {
        if (!date || !(date instanceof Date)) return null;
        return date.toISOString();
    },

    /**
     * List all accounts.
     * @returns {Object[]} Array of {name, id} objects
     */
    listAccounts() {
        const accounts = Mail.accounts();
        const names = Mail.accounts.name();
        const ids = Mail.accounts.id();
        const results = [];
        for (let i = 0; i < accounts.length; i++) {
            results.push({ name: names[i], id: ids[i] });
        }
        return results;
    },

    /**
     * List mailboxes for an account.
     * Note: messageCount is not available via batch fetch, only unreadCount.
     * @param {Account} account - Mail account
     * @returns {Object[]} Array of {name, unreadCount}
     */
    listMailboxes(account) {
        const mboxes = account.mailboxes();
        const names = account.mailboxes.name();
        const unread = account.mailboxes.unreadCount();
        const results = [];
        for (let i = 0; i < mboxes.length; i++) {
            results.push({
                name: names[i],
                unreadCount: unread[i],
            });
        }
        return results;
    },
};
