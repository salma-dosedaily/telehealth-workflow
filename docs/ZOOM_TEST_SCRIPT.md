# Zoom Test Script — Full Flow

Use this script when testing the telehealth pipeline. Play it **by audio** during a Zoom call (Cloud Recording + Audio transcript on). The pipeline will extract the line after **"Summary for the email:"** and send it to RudderStack → Klaviyo.

**Requirements:** Meeting must run **at least 5 minutes** and the transcript must have **at least 50 words**. This script is ~120 words; read it at a normal pace. If the call is under 5 minutes, start the meeting, wait until 5 minutes have passed, then read the script and end the meeting.

---

## Script (read aloud or play via TTS)

**[Opening — optional]**

Thanks for joining today. We've covered your questions and next steps. Here’s a quick recap so you have it in writing.

**[Main — required for extraction]**

I’ll send you a follow-up email with a short summary. Summary for the email: Please remind the patient to take their vitamins daily and to book a follow-up in four weeks. Thank you again and we’ll talk soon.

**[Closing — optional]**

That’s all for this session. Take care.

---

## Short version (minimal, ~35 words — add a sentence if you need 50+)

I’ll send a follow-up. Summary for the email: Please remind the patient to take their vitamins and book a follow-up in four weeks. Thanks and take care.

*(Pipeline needs 50+ words in the transcript; the full script above is safe. If you use the short version, add one or two extra sentences of filler.)*

---

## Custom test note

To verify the note in Klaviyo, change the text after **Summary for the email:** to something unique, e.g.:

- *Summary for the email: This is a test. Please send the patient a reminder to drink more water and schedule their next appointment.*

Use that same text when checking the post-call email in Klaviyo.

---

## Free tools to read the script aloud (TTS)

| Tool | Platform | Notes |
|------|----------|--------|
| **Natural Reader** | Web, desktop | Free tier: paste text, play. https://www.naturalreaders.com |
| **Google Translate** | Web | Paste text, click speaker icon to read aloud. |
| **Speak** (macOS) | Mac | Select text → Right-click → **Speech** → **Start Speaking**. Or System Settings → Accessibility → Spoken Content → Speak selection. |
| **Narrator** (Windows) | Windows | Win + Ctrl + Enter to toggle; reads selected text. |
| **Balabolka** | Windows | Free desktop TTS; save as WAV/MP3 and play in Zoom. http://www.cross-plus-a.com/balabolka.htm |
| **TTSFree.com** | Web | Paste text, choose voice, play or download MP3. |

**Tip:** For Zoom, the simplest is **Natural Reader** or **Google Translate** in a browser tab with your mic set to “same as system” or by playing the TTS output through your speakers so Zoom picks it up. Alternatively, export to MP3 and play the file during the call.
