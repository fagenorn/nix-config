# ADR-console-026 — The owner removes an account from the page

Context: removing an account meant `claude-account rm` in a terminal, which left the stored login behind, and left the console's pin, exclusion and sign-in item for a profile that no longer exists. Decision: Remove on the page needs the typed name. It marks the profile so that no run starts under it, signs it out with the client, then deletes it only through the launcher's `rm`, and lifts its pin and exclusion. Rejected: the terminal `rm` alone, and deleting without signing out first.
