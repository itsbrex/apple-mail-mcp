# Apple Mail

This context describes mail organized in Apple Mail and the boundaries for
finding, reading, and changing it.

## Language

### Accounts and mailboxes

**Mail account**:
A mail account configured in Apple Mail that contains mailboxes and can have
one or more email addresses.
_Avoid_: User, customer, email address used as an account identity

**Account name**:
The human-readable name of a mail account, such as Work or Personal;
account exclusions match this name exactly, including case.
_Avoid_: Account ID, email address

**Account ID**:
The identity assigned to a mail account by Apple Mail, distinct from its
human-readable name and email addresses.
_Avoid_: Account name, sender address

**Mailbox**:
A named collection of emails within a mail account; identically named
mailboxes in different accounts are distinct collections.
_Avoid_: Account, folder without its mail-account context

### Emails and identity

**Email**:
A message held in Apple Mail, with a subject, sender, body, and any
attachments; copies in different mailboxes are distinct mailbox entries.
_Avoid_: Item, record, conversation used for a single email

**Mail message ID**:
The numeric identifier Apple Mail uses to locate an email within a mailbox;
its meaning depends on the mail account and mailbox.
_Avoid_: Globally unique email ID, Internet Message-ID, unqualified message ID

**Email reference**:
A Mail message ID together with its mail account and mailbox, distinguishing
emails that share a numeric identifier in different locations.
_Avoid_: Bare ID used as a complete identity

**Internet Message-ID**:
The identifier carried in an email's Message-ID header, when present;
multiple copies of an email may carry the same value.
_Avoid_: Mail message ID, mailbox locator

**Email body**:
The main text of an email, distinct from its subject and the contents of
attached files.
_Avoid_: Entire email, attachment content

**Attachment**:
A file or inline resource carried by an email, with a filename and available
descriptive details; the filename alone does not identify the parent email.
_Avoid_: Hyperlink, email body

### Mail state and outgoing mail

**Read status**:
Whether Apple Mail marks an email as read or unread, independently of its
flag status.
_Avoid_: Seen by the recipient, flag status

**Flag status**:
Whether an email is marked for attention, independently of whether it is
read or unread.
_Avoid_: Read status, importance inferred from the email's content

**Mailbox move**:
A change of an email's mailbox within the same mail account; archiving and
moving to Trash are moves to destination mailboxes.
_Avoid_: Permanent deletion, cross-account transfer

**Draft**:
An unsent outgoing email saved in Apple Mail; creating a draft is a mail
change even though delivery has not been requested.
_Avoid_: Preview, sent email

**Send confirmation**:
Explicit authorization to send a newly composed email with the supplied
content and recipients; it does not select or send a previously saved draft.
_Avoid_: Draft approval token, confirmation of recipient delivery

**Sent status**:
An outcome indicating that Apple Mail accepted the send request, without
establishing delivery to or receipt by the recipients.
_Avoid_: Delivered, received, read

### Access boundaries

**Excluded account**:
A mail account intentionally hidden from mail discovery, reading, searching,
and changes through this service.
_Avoid_: Mailbox exclusion, account omitted only from search

**Mailbox exclusion**:
A rule omitting selected mailboxes from indexing or search results; it does
not hide their mail account or prohibit direct mail access.
_Avoid_: Excluded account, access restriction

**Read-only mail access**:
Access that permits finding and reading mail while prohibiting changes to
mail, including drafts, sends, mailbox moves, and status changes.
_Avoid_: No local writes, frozen search information

### Search boundaries

**Search scope**:
The parts of an email selected for matching: subject, sender, body, or
attachment filenames; all-fields search covers subject, sender, and body.
_Avoid_: Mailbox selection, attachment-content search, every possible field

**Search coverage**:
The set of emails a search can examine; local availability, exclusions,
mailbox limits, unreadable mail, and changes awaiting refresh can narrow it.
_Avoid_: All remote mail, complete coverage inferred from an uncapped index

**Search freshness**:
The recency of the last recorded search refresh; a recent refresh does not
prove complete coverage or that every mailbox is current.
_Avoid_: Complete coverage, fully up to date

**No match**:
A search outcome in which no email matches within the coverage and filters
actually searched; it does not establish that the email does not exist.
_Avoid_: Mailbox empty, index unavailable, email absent everywhere
