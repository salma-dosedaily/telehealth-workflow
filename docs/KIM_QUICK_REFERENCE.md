# Quick Reference Guide for Kim

**Updated:** 2026-04-03
**Aligned with:** `CHANGELOG.md` (Slack, Klaviyo, form event shape, reminders, No Show)

---

## What Changed (recent)

### 1. Product-specific follow-up emails
**What it means:** customers can get the right follow-up path based on consultation type (Liver, Cholesterol, or Bundle).

**What you do:** Use a **Product** (or **Program**) field on the form when it’s there. Calendly / Zoom **meeting topic** can also carry keywords (liver, cholesterol, bundle) so the system can infer product when the form doesn’t ask.

### 2. No-shows and short calls
**What it means:**
- On the **form**: if **call duration** is under **5 minutes**, we **do not** send the normal follow-up event (treated like a no-show for that path).
- From **Zoom** alone: calls under **10 minutes** send a no-show signal to marketing automatically.
- **Manual No Show (new):** You can now select **"No Show"** from the **Product/Program** dropdown on the form to manually log a no-show — even if you have no notes and no duration. The customer will automatically receive a **"We Missed You"** email via Klaviyo. You only need to fill in their **email**.

**What you do:**
- For missed calls: select **No Show** from the Product/Program dropdown, fill in the customer email, and submit. Notes and duration are optional.
- For real calls: enter a realistic duration (≥ 5 min) as usual.

### 3. customer tracking (completed calls)
**What it means:** Profiles can be tagged when a completed form submission goes through so the team can segment who has finished a telehealth call.

**What you do:** Keep submitting the form after real calls (duration ≥ 5 when you enter it).

### 4. Notes as bullet-style lines in the customer email
**What it means:** Numbered items (`1. … 2. …`) or line breaks in your note are turned into **bullet lines** for the follow-up email template.

**What you do:** Type notes naturally—dashes, numbers, or line breaks are fine. The marketing email template must use Klaviyo’s **`linebreaksbr`** filter on `kims_custom_note` (not `nl2br`) so line breaks show correctly—your tech team sets that.

### 5. Slack reminder: Name and Email
**What it means:** The ~15-minute Slack reminder shows **Name** and **Email** as **separate** lines (name is no longer shown in the “Name” slot by mistake).

**What you do:** Same as before—use the Zoom link and the prefilled form link from Slack.

---

## Your workflow

### Before the call
1. Check Slack for your **~15-minute** reminder.  
2. Use **Join Zoom meeting** and keep **Open prefilled Telehealth Note form** for after the call.

### During the call
- Run the consultation. You can use bullets or numbered points in your head or on paper—same as you’ll type in the form.

### After the call
1. Open the **prefilled** form link (from Slack or email).  
2. Confirm **email** and **name** (or fix if wrong).  
3. Fill **Kim’s Note** (summary for the customer).  
4. **Duration** — if the form asks, use real minutes (**≥ 5** for normal follow-up). If there’s no duration field, defaults apply.
5. Paste **Zoom link or meeting UUID** in the meeting field when you have it (helps tie the visit to the booking).
6. Choose **product** if the form has that field (Liver, Cholesterol, Bundle — or **No Show** for missed calls).
7. **Submit.**

> **No Show shortcut:** If the patient didn’t show up, select **No Show** from the Product/Program dropdown. You only need their email — skip notes and duration. They will automatically get a "We Missed You" email.

---

## Tips for notes (bullets and lists)

**Examples that work well:**

```
Next steps:
- Start meal plan Monday
- Drink 8 glasses of water daily

Or numbered:
1. Increase protein
2. Walk 30 minutes daily
```

**Works:** dashes, numbers, line breaks, short paragraphs.  
**Avoid:** nothing special—type naturally.

---

## Troubleshooting

| Issue | What to check |
|--------|----------------|
| Bullet lines don’t look right in the customer email | Tech: Klaviyo HTML template should use the **linebreaksbr** filter on **event.kims_custom_note** (see `docs/KLAVIYO_POST_CALL_EMAIL_SETUP.md`). Do **not** use `nl2br`—it breaks the template. |
| Wrong product email branch | Calendly title / Zoom topic includes **Liver**, **Cholesterol**, or **Bundle**; or select product on the form. |
| No Show customer didn’t get "We Missed You" email | Confirm you selected exactly **No Show** (capital N, capital S) from the dropdown and entered their email correctly. Ask tech to check Klaviyo event activity. |
| customer didn’t get the follow-up | Form was submitted; duration **≥ 5** if you entered one; customer email correct; ask tech to check Klaviyo **skipped** reason. |
| No Slack reminder | ~15 min before start; Calendly event should use Zoom location; ask admin if reminder job/Slack is configured. |
| Form missing name/email | Use the **Slack link for that booking**, not an old bookmark. |

---

## Benefits for you

1. Less typing when duration is optional on the form.
2. Clearer Slack reminder (**Name** + **Email**).
3. Notes can read as a neat list in email when the template is set up correctly.
4. Product routing when the form or meeting context includes it.
5. **No Show in one step** — select No Show from the dropdown, enter their email, submit. No notes or duration needed. "We Missed You" email goes out automatically.

---

## Need help?

- **Tech / Slack / Klaviyo:** your data or ops contact.  
- **Form field names:** see `docs/NUTRITIONIST_INSTRUCTION_MANUAL.md` and `docs/FORM_MEETING_UUID_SETUP.md`.
