from pathlib import Path
p = Path("src/aidaily/history.py")
s = p.read_text(encoding="utf-8")

# `folded_now` strips punctuation and spaces, which is right for hashing but wrong for the
# message comparison: the event-type check reads verbs, and folding welds them to the next word.
old = """                if key.startswith("m:"):
                    # A shared actor set is only a *candidate*: the stored headline has to
                    # describe the same kind of event. "DeepSeek ships V4.1-Flash" and
                    # "DeepSeek had a five-hour outage" name one actor and are two stories.
                    if not _same_message_as(folded_now, self._titles.get(key, ())):
                        continue"""

new = """                if key.startswith("m:"):
                    # A shared actor set is only a *candidate*: the stored headline has to
                    # describe the same kind of event. "DeepSeek ships V4.1-Flash" and
                    # "DeepSeek had a five-hour outage" name one actor and are two stories.
                    #
                    # The **raw** title is compared, not `folded_now`: folding strips the
                    # separators that keep a verb readable as a verb, and the event-type check
                    # depends on seeing them.
                    if not _same_message_as(event.title, self._titles.get(key, ())):
                        continue"""

assert s.count(old) == 1, "message branch"
s = s.replace(old, new, 1)
p.write_text(s, encoding="utf-8")
print("raw title used for the message check")