# ADR-console-072 — A question card has one send that carries the option and the owner's words

Context: an owner picked Ask for changes, typed what to change and sent, and the words were lost (#1242). Decision: a question card has one send that carries the option, the owner's words or both; the manager marks in `needs_words` the options that need words, which the card and the service refuse without them; words never make an answer differ. Rejected: two sends with two payloads, and guessing from an option's label which one needs words.
