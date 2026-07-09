# Open Neuromorphic: Volunteer Ticket Resolution Guide

Welcome to the Content Ops team! We use an AI-assisted Discord bot to make triaging and resolving GitHub issues incredibly fast. Instead of manually cloning repositories, formatting Markdown, resizing logos, and wrestling with `git push`, the bot does the heavy lifting. You supply the human judgement.

This guide walks you through the end-to-end flow of finding an issue, generating a draft, reviewing it, and getting it pushed to production.

---

## Prerequisites

To use these commands, you must:
1. Have the **Volunteer Technical** or **Volunteer Content** role in the Discord server.
2. Have **Server DMs Enabled**. The bot will send you draft files privately so you can review them before they are pushed publicly.
3. Ensure your Discord username is mapped to your GitHub username in the server's Entity Glossary (ask a server admin to link you if you get "I don't know your GitHub handle" errors).

---

## Step 1: Find an Issue to Work On

You don't even need to leave Discord to see what needs doing.

- Run `/onm-project list-issues repo:Website` to see the 10 most recent open issues.
- Run `/onm-project my-issues repo:Website` to see tickets specifically assigned to you.

Once you find a ticket you want to tackle, note the **Issue Number** (e.g., `#454`).

---

## Step 2: Get Context (Optional)

If a ticket references an internal meeting or previous technical discussion that you weren't present for, you can ask the bot to dig through the organization's private archives to summarize the context for you.

- Run `/onm-ticket context repo:Website issue_num:454`
- The bot will read the issue, scan our library of transcripts and chat logs, and reply with a synthesized brief outlining the background you need to solve the ticket.

---

## Step 3: Generate a Draft

Once you are ready to resolve the ticket, tell the bot to draft the content for you:

- Run `/onm-pr preview issue_num:454`
- The bot will:
  1. Fetch the GitHub issue and all of its comments.
  2. Clone the website repository to read our exact Markdown schemas and categories.
  3. Pre-fetch any images linked in the issue.
  4. Have a multimodal AI write the complete Markdown file and select the primary logo.
- *This process takes roughly 15 to 30 seconds.*

---

## Step 4: Review the Draft

When the bot finishes, it will send you a **Direct Message** containing:
- The generated Markdown file (e.g., `preview_content_software_snn-mlir.md`).
- Any images the AI decided to download and include (e.g., `logo.png`).
- A summary of what it did, and a list of alternative images it found but ignored.

**Your Job:** Open the `.md` file on your computer and read it.
- Did it pick the correct Hugo category?
- Did it incorporate corrections mentioned in the GitHub comments?
- Did it select the correct logo, or did it accidentally pick a screenshot of a UI?

---

## Step 5: Approve, Reject, or Change Images

At the bottom of the DM, you will see three interactive buttons:

🟩 **[ Approve & Create PR ]**
Click this if the draft is perfect. The bot will automatically:
1. Push the branch to the staging server.
2. Open a Pull Request on the main repository.
3. Reply to you with a link to the PR and a link to the live Staging Preview.

🟥 **[ Reject / Cancel ]**
Click this if the draft is completely wrong. It will instantly delete the cached files and abort the operation.

⬜ **[ Change Images ]**
If the text is great but the AI picked the wrong image (or ignored a valid image), click this button.
- A popup window will appear asking for **Candidate IDs**.
- Look at the text in the DM for "Discovered Candidates" (e.g., `img_1`, `img_2`).
- Type the ID of the correct image (or multiple IDs separated by commas, like `img_1, img_2` for a logo and a dark-mode variant).
- If you want to strip all images out entirely, type `clear`.
- Submit the popup, and the bot will re-download the correct images and send you a fresh DM to approve!

---

## Step 6: Follow Up on GitHub

Once you click **Approve & Create PR**, you are done with Discord! 

Click the PR link provided by the bot. A repository maintainer will review the code natively on GitHub. If they request changes, you can push commits directly to the branch the bot created for you, or they will merge it directly into the live website.