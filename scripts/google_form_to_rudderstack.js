/**
 * Google Apps Script - Sends Google Form responses to the Telehealth Cloud Function.
 * The Cloud Function verifies patient email, optionally ties to Zoom meeting, and sends to RudderStack → Klaviyo.
 *
 * SETUP:
 * 1. Create a Google Form with these fields:
 *    - "Email" or "Patient Email" (short answer, required) - Script detects any field with "email"
 *    - "Kim's Note" (paragraph, required) - Script detects fields with "note" or "summary"
 *    - "Name" or "Patient Name" (short answer, optional) - Script detects any field with "name" (excluding product/program name)
 *    - Optional: "Call duration (minutes)" - if omitted, a default is used (Kim does not have to enter duration)
 *    - "Meeting UUID" or "Zoom Link" (short answer, optional) - Kim pastes the Zoom meeting UUID or join URL here to tie the form
 *      to the Zoom meeting; the event will then include host_email and meeting_date from Firestore.
 *    - Optional: "Product" or "Program" (dropdown/list) - e.g. Liver, Cholesterol, Bundle, No Show. Sent as productName
 *      so Klaviyo flow splits (e.g. productName contains Liver) can route the follow-up email.
 *      Selecting "No Show" bypasses the note and duration requirements and fires Telehealth_Call_Finished
 *      with productName="No Show" so Klaviyo can split and send the "We Missed You" email.
 *
 * 2. Open the Form → 3 dots menu → Script editor → paste this code.
 *
 * 3. Set TELEHEALTH_WEBHOOK_URL to your Cloud Function URL (same as Zoom webhook).
 *
 * 4. FORM_SUBMIT_SECRET: Create in GCP with ./scripts/setup_firestore_form_secret.sh, then set the
 *    SAME value here so only your form can call the endpoint. If empty, the endpoint accepts form
 *    submissions without the header (less secure).
 *
 * 5. Triggers > Add Trigger: onFormSubmit, From form, On form submit.
 *
 * Duration: If the form has no duration field, DEFAULT_DURATION_MINUTES is sent so Kim does not need to enter it.
 * See docs/FORM_MEETING_UUID_SETUP.md for Firestore + FORM_SUBMIT_SECRET setup when using Meeting UUID.
 *
 * Meeting UUID field: Kim can paste either the Zoom meeting UUID or a Zoom join link
 * (e.g. https://us06web.zoom.us/j/89166792057?pwd=...); the script extracts the meeting ID from URLs.
 */

/**
 * If the value is a Zoom join URL, extract the numeric meeting ID; otherwise return trimmed value as-is.
 * Supports patterns like: https://us06web.zoom.us/j/89166792057?pwd=... or https://zoom.us/j/89166792057
 */
function normalizeMeetingIdentifier(value) {
  if (!value || typeof value !== "string") return "";
  var trimmed = value.trim();
  var match = trimmed.match(/zoom\.us\/j\/(\d+)/i);
  return match ? match[1] : trimmed;
}

// ========== CONFIGURATION ==========
// Cloud Function URL (same as Zoom webhook endpoint)
const TELEHEALTH_WEBHOOK_URL = "https://us-central1-dosedaily-raw.cloudfunctions.net/telehealth_webhook_handler";
// Optional: must match FORM_SUBMIT_SECRET in Cloud Function env (GCP Secret Manager)
const FORM_SUBMIT_SECRET = "660f46539a8bc7983b84ec19a345e9f9946c7ba52e0521b9";
// When form has no "duration" field, use this so Kim does not need to enter meeting duration.
const DEFAULT_DURATION_MINUTES = 10;
// If form includes duration and it's below this, treat as no-show and do not send.
const MIN_DURATION_MINUTES = 5;
// ====================================

function onFormSubmit(e) {
  try {
    const responses = e.response.getItemResponses();
    let patientEmail = "";
    let kimsNote = "";
    let patientName = "";
    let callDurationMin = -1;
    let meetingUuid = "";
    let productName = "";  // ← NEW: Added product field

    responses.forEach(function (itemResponse) {
      const question = itemResponse.getItem().getTitle().toLowerCase();
      const answer = itemResponse.getResponse();
      // Match "email" field (works with "Email", "Patient Email", "email address", etc.)
      if (question.includes("email")) {
        patientEmail = answer;
      // Match "note" or "summary" for Kim's notes
      } else if (question.includes("note") || question.includes("summary")) {
        kimsNote = answer;
      // Match "name" field but exclude "product name" or "program name"
      } else if (question.includes("name") && !question.includes("product") && !question.includes("program")) {
        patientName = answer;
      // Match duration field
      } else if (question.includes("duration") || question.includes("minute")) {
        callDurationMin = parseInt(answer, 10) || 0;
      // Match meeting UUID or Zoom link field
      } else if (question.includes("uuid") || question.includes("meeting") || question.includes("zoom")) {
        meetingUuid = (answer && typeof answer === "string") ? normalizeMeetingIdentifier(answer) : "";
      // Match product or program field
      } else if (question.includes("product") || question.includes("program")) {
        productName = (answer && typeof answer === "string") ? answer.trim() : "";
      }
    });

    // Canonical email for RudderStack userId / Klaviyo merge (matches main.py _normalize_email_for_identity).
    if (patientEmail && typeof patientEmail === "string") {
      patientEmail = patientEmail.trim().toLowerCase();
    } else {
      patientEmail = "";
    }

    // "No Show" selected in the Product/Program dropdown — only email is required.
    const isNoShow = productName.toLowerCase().replace(/[-\s]/g, "") === "noshow";

    if (!patientEmail) {
      Logger.log("Missing required field: email");
      return;
    }
    if (!isNoShow && !kimsNote) {
      Logger.log("Missing required field: note");
      return;
    }
    // No Show submissions skip duration checks — Kim explicitly marked them as no-shows.
    if (!isNoShow) {
      // If form has no duration field, use default so Kim does not need to enter it
      if (callDurationMin < 0) {
        callDurationMin = DEFAULT_DURATION_MINUTES;
      }
      if (callDurationMin < MIN_DURATION_MINUTES) {
        Logger.log("Skipped (no-show): duration " + callDurationMin + " min < " + MIN_DURATION_MINUTES + " min for " + patientEmail);
        return;
      }
    }

    // Payload expected by Cloud Function process_form_submission()
    // Uses "email" and "name" only (not patient_* aliases) for HIPAA compliance.
    const payload = {
      email: patientEmail,
      name: patientName || "",
      kims_custom_note: kimsNote,
      duration: callDurationMin
    };
    if (meetingUuid) {
      payload.meeting_uuid = meetingUuid;
    }
    if (productName) {  // ← NEW: Include product in payload
      payload.product_name = productName;
    }

    const headers = { "Content-Type": "application/json" };
    if (FORM_SUBMIT_SECRET) {
      headers["X-Form-Secret"] = FORM_SUBMIT_SECRET;
    }

    const options = {
      method: "POST",
      contentType: "application/json",
      headers: headers,
      payload: JSON.stringify(payload),
      muteHttpExceptions: true
    };

    const response = UrlFetchApp.fetch(TELEHEALTH_WEBHOOK_URL, options);
    const responseCode = response.getResponseCode();

    if (responseCode === 200) {
      Logger.log("Successfully sent to Telehealth webhook: " + patientEmail);
    } else {
      Logger.log("Telehealth webhook error: " + responseCode + " - " + response.getContentText());
    }
  } catch (error) {
    Logger.log("Error in onFormSubmit: " + error.toString());
  }
}

// Test function - run manually to verify Cloud Function form endpoint
function testTelehealthWebhook() {
  const testPayload = {
    patient_email: "test@example.com",
    patient_name: "Test Patient",
    kims_custom_note: "Test note from Google Form.",
    duration: DEFAULT_DURATION_MINUTES
  };
  const headers = { "Content-Type": "application/json" };
  if (FORM_SUBMIT_SECRET) {
    headers["X-Form-Secret"] = FORM_SUBMIT_SECRET;
  }
  const response = UrlFetchApp.fetch(TELEHEALTH_WEBHOOK_URL, {
    method: "POST",
    contentType: "application/json",
    headers: headers,
    payload: JSON.stringify(testPayload),
    muteHttpExceptions: true
  });
  Logger.log("Response: " + response.getResponseCode() + " - " + response.getContentText());
}
