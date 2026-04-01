# Klaviyo Email Delivery Verification

**Issue:** Email sent but can't see delivery confirmation  
**Status:** Email likely delivered - just need to check the right place

---

## ✅ Quick Verification Steps

### Step 1: Check Flow Analytics
1. Go to Klaviyo → **Flows**
2. Click **"Telehealth-Post-Call Follow-Up Email"**
3. Look at the flow canvas
4. You should see numbers on each step:
   ```
   Trigger: 1 (or more)
      ↓
   Conditional Split: 1
      ↓
   Email (Liver): 1 Sent, 1 Delivered
   ```

### Step 2: Check Profile Timeline
1. Go to **Profiles** → Search for the email address
2. Click on the profile
3. Go to **Timeline** tab
4. Look for these events (most recent at top):
   ```
   ✅ Email Delivered: Telehealth-Post-Call Follow-Up Email
   ✅ Email Sent: Telehealth-Post-Call Follow-Up Email
   ✅ Entered Flow: Telehealth-Post-Call Follow-Up Email
   ✅ Telehealth_Call_Finished event received
   ```

### Step 3: Check Your Inbox
1. Check the email inbox for the patient email address
2. Look in:
   - Inbox
   - Spam/Junk folder
   - Promotions tab (if Gmail)

---

## 🔍 What to Look For

### In Flow View:
- **Numbers on each step** - Shows how many people went through
- **Green checkmarks** - Indicates successful sends
- **"View Analytics"** button - Click for detailed stats

### In Profile Timeline:
- **Event icon** (⚡) - Shows `Telehealth_Call_Finished` was received
- **Email icon** (✉️) - Shows email was sent
- **Delivered status** - Confirms email reached inbox
- **Opened status** - Shows if email was opened

### In Analytics:
- **Flow Performance** report
- **Email Performance** report
- Filter by date to see recent sends

---

## 📧 Common Reasons You Might Not See It

### 1. Looking in Wrong Place
**Issue:** Viewing preview instead of actual sends  
**Fix:** Go to Flow Analytics or Profile Timeline (not preview)

### 2. Email in Spam
**Issue:** Email delivered but went to spam folder  
**Fix:** Check spam/junk folder in the recipient's inbox

### 3. Timing Delay
**Issue:** Just sent, delivery status updating  
**Fix:** Wait 1-2 minutes and refresh the page

### 4. Test Email vs Real Email
**Issue:** Looking at test sends instead of flow sends  
**Fix:** Check the profile that received the actual flow email

---

## 🎯 Expected Flow in Klaviyo

### What Should Happen:
```
1. RudderStack sends event
   ↓
2. Klaviyo receives: Telehealth_Call_Finished
   Properties: {
     patient_email: "salma@dosedaily.co",
     productName: "Liver",
     kims_custom_note: "1. note one 2. note 2",
     source: "google_form"
   }
   ↓
3. Flow triggers (source = google_form)
   ↓
4. Conditional split checks productName
   ↓
5. Routes to "Liver" email
   ↓
6. Email sent
   ↓
7. Email delivered
```

### Where to See Each Step:

| Step | Where to Check |
|------|---------------|
| Event received | Profile → Timeline → Look for ⚡ Telehealth_Call_Finished |
| Flow triggered | Flow → Analytics → Trigger count |
| Conditional split | Flow → Analytics → Each branch count |
| Email sent | Profile → Timeline → Look for ✉️ Email Sent |
| Email delivered | Profile → Timeline → Look for ✅ Email Delivered |
| Email opened | Profile → Timeline → Look for 👁️ Email Opened |

---

## 🧪 Test Verification

### Quick Test:
1. **Submit another test form** with your email
2. **Go to Klaviyo immediately**
3. **Navigate to:** Profiles → Search your email
4. **Watch the Timeline** - events appear in real-time
5. **You should see:**
   - Event received (within seconds)
   - Flow entered (within seconds)
   - Email sent (within 1-2 minutes)
   - Email delivered (within 2-5 minutes)

---

## 📊 Screenshots to Take

To verify everything is working, take screenshots of:

### 1. Flow Analytics
- Go to Flows → Your flow
- Take screenshot showing the numbers on each step

### 2. Profile Timeline
- Go to Profiles → Search email → Timeline
- Take screenshot showing the events

### 3. Email in Inbox
- Check the actual email inbox
- Take screenshot of the received email

---

## ✅ Success Indicators

You'll know it's working when you see:

### In Klaviyo Flow:
- ✅ Trigger count > 0
- ✅ Email step shows "Sent: X"
- ✅ Email step shows "Delivered: X"

### In Profile:
- ✅ Event `Telehealth_Call_Finished` in timeline
- ✅ "Entered Flow" in timeline
- ✅ "Email Sent" in timeline
- ✅ "Email Delivered" in timeline

### In Email Inbox:
- ✅ Email appears in inbox
- ✅ Subject line correct
- ✅ Content shows with proper formatting
- ✅ Merge variables filled correctly

---

## 🆘 Still Can't Find It?

### Check These:

1. **Flow is Live**
   - Go to Flow → Check status is "Live" (not Draft)

2. **Trigger Filter**
   - Go to Flow → Trigger settings
   - Verify: `source equals google_form`

3. **Profile Exists**
   - Search for the email in Profiles
   - If not found, event didn't reach Klaviyo

4. **RudderStack Logs**
   - Check RudderStack dashboard
   - Verify event was sent to Klaviyo destination

5. **Cloud Function Logs**
   ```bash
   gcloud functions logs read telehealth_webhook_handler \
     --project=dosedaily-raw \
     --limit=20
   ```
   Look for: "Success: Telehealth_Call_Finished sent to RudderStack"

---

## 💡 Pro Tip

The easiest way to verify everything is working:

1. **Submit a test form** with YOUR email address
2. **Go to Klaviyo** → Profiles → Search YOUR email
3. **Click on your profile**
4. **Go to Timeline tab**
5. **Refresh every 30 seconds**
6. **Watch the events appear in real-time!**

You'll see:
- Event received ✅
- Flow entered ✅
- Email sent ✅
- Email delivered ✅

Then check your actual email inbox - the email will be there! 📧

---

## 📞 Need Help?

If you still can't see the delivered email after checking these places:
1. Take a screenshot of the Flow Analytics
2. Take a screenshot of the Profile Timeline
3. Check if the email is in your spam folder
4. Verify the flow status is "Live"

The email in your screenshot looks perfect - it's definitely being sent! You just need to check the right place to see the delivery confirmation. 🎉
