# Techset LeadGen — user guide

Techset LeadGen is a desktop application. Everything happens in its own window; no browser is needed.

## Signing in

- **First start on a computer:** enter your organization's name and create the first administrator account (password of at least 12 characters). Existing sales, leads, and clients stay as they are.
- **Every later start:** sign in with your email and password. After 5 wrong passwords the account waits 15 minutes.
- **New colleague:** an administrator opens **Users → Invite user** and gives you a one-time code (in person or by phone). On the sign-in screen choose **I have an activation or password-reset code**, enter it, and choose your password.
- **Forgot your password:** ask an administrator for a reset code (**Users → Issue password-reset code**). If no administrator can sign in, someone with access to the computer runs `TechsetLeadGen --issue-reset-code their@email` and uses the printed code.
- You are signed out after 30 minutes without using the app, after 12 hours at most, and immediately if an administrator changes your role or deactivates your account.

## Where things are

| Area | Use it to |
|---|---|
| **Dashboard** | See sales, client, and lead totals, and **My work**: your overdue and due-today tasks, your open leads, and new leads nobody owns. Each button opens the matching list. Import data and download import templates. |
| **Sales** | Filter and compare sales, see trends and top clients and products, and export an HTML report. |
| **Leads** | Funnel and marketing performance (cost per lead, per client, ROI) and the lead list. **Open** a lead for its details, timeline, and tasks; **Stage…** moves it on; **New lead** adds one by hand; select rows and **Assign selected…** to give them an owner; **Owner** filters to *My leads* or *Unassigned*. |
| **Clients** | Search clients, see their sales and latest lead, add or edit them (the **Account** tab holds owner, status, industry, website), open the profile for **Contacts**, **Leads**, **Activity**, and **Tasks**, merge duplicates, export a client report. |
| **Tasks** | Your follow-ups (or everyone's, for managers): due today, overdue, next 7 days, completed. A lead's next follow-up is its earliest open task. |
| **Users** | (Administrators) invite people, change roles, deactivate accounts, issue codes. |
| **Audit log** | (Super Admin) who changed what, when, from which computer. |
| **Settings** | Your name, time zone, and password; the organization name; where the database is and **Back up now…**. |

The search box at the top (Ctrl+K) finds clients, their contacts, and leads. Ctrl+1 to Ctrl+8 open the areas in sidebar order, Ctrl+I starts an import.

## Working with lists

- **Sort** by clicking a column heading; click again to reverse. Dates and amounts sort by value.
- **Hover** over a shortened entry ("Globex Corpo…") to read it in full; drag a heading's edge to widen a column.
- **Choose columns:** right-click any heading to show or hide columns, or choose **Reset columns**. The app remembers your choice. In the client list, Tax ID and Email start hidden because the list masks them anyway; the client profile shows them.
- **Copy:** select rows (Ctrl or Shift + click where several are allowed) and press Ctrl+C; paste into a spreadsheet, with headings.
- **Open:** double-click a row or press Enter. Right-click a row in the lead or client list for its actions.
- Stages, priorities, and statuses appear as coloured labels: green for good outcomes (Qualified, Client, Done, Active), amber for attention (Meeting, High, Invited), red for Lost, Urgent, and failed sign-ins. Overdue task dates are red.
- **Audit log:** type part of an action's name (for example "stage changed" or "sign-in") to filter it; each entry names the record and the people involved.

## Lead stages

Lead → Contacted → Meeting → Qualified → Client, with Nurture (not now, later) and Lost along the way. Only sensible moves are offered. **Qualified** and **Lost** need a reason, which stays in the lead's timeline. A lead can be marked **Client** only once it is linked to a client. Imported files may use either the stage names above or their codes.

## Roles

"Own" means records assigned to you (or that you created and nobody owns yet). Anyone may take an unassigned lead or client for themselves.

| Can… | Super Admin | Sales Manager | Lead Researcher | BDR / Account Executive | Marketing | Management (read-only) |
|---|---|---|---|---|---|---|
| See analytics, leads, clients | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| See tax IDs, emails, phone numbers | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| Add clients and leads | ✓ | ✓ | ✓ | ✓ | — | — |
| Edit clients and their contacts | all | all | all | own | — | — |
| Edit leads and move stages | all | all | own | own | — | — |
| Qualify or mark leads Lost | all | all | — | own | — | — |
| Assign owners to others | ✓ | ✓ | — | — | — | — |
| Delete or merge clients | ✓ | ✓ | — | — | — | — |
| Log activity | ✓ | ✓ | ✓ | ✓ | — | — |
| Tasks | all | all | own | own | own | view all |
| Marketing spend | ✓ | ✓ | — | — | ✓ | — |
| Import data | ✓ | ✓ | ✓ | — | ✓ | — |
| Export reports | ✓ | ✓ | — | — | ✓ | ✓ |
| Clear all sales/leads/clients | ✓ | — | — | — | — | — |
| Users, audit log, organization, backups | ✓ | users (view) | — | — | — | — |

The application hides what your role cannot do, and the same rules are checked again whenever data is saved.

## Backups

Settings → **Back up now…** writes a consistent copy of the whole database while the app is open. The app also copies the database to `data/backups/` before installing an update that changes its structure. To restore, close the app and replace `data/sales.db` with the backup copy.
