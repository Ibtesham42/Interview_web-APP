const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

(async () => {
  const browser = await chromium.launch({ headless: false, slowMo: 500 });
  const context = await browser.newContext({ viewport: { width: 1400, height: 900 } });
  const page = await context.newPage();

  console.log('=== AI Mock Interview E2E Test ===\n');

  try {
    // Navigate to app
    console.log('1. Opening http://localhost:3000...');
    await page.goto('http://localhost:3000', { waitUntil: 'networkidle' });
    await page.screenshot({ path: 'step1_homepage.png', fullPage: true });
    console.log('   Homepage loaded and screenshot saved.\n');

    // Check for errors in console
    page.on('console', msg => {
      if (msg.type() === 'error') console.log('   [Browser Error]:', msg.text());
    });

    // Check if upload form is visible
    console.log('2. Looking for Candidate Upload form...');
    await page.waitForSelector('.upload-zone', { timeout: 5000 });
    await page.screenshot({ path: 'step2_upload_form.png', fullPage: true });
    console.log('   Upload form found.\n');

    // Enter candidate name
    console.log('3. Entering candidate name...');
    await page.fill('input[placeholder="Enter candidate name"]', 'Ahmad Test Candidate');
    await page.screenshot({ path: 'step3_name_entered.png', fullPage: true });

    // Create a test PDF (simple text file renamed)
    const testPdfPath = path.join(__dirname, 'test_resume.pdf');
    const dummyPdfContent = Buffer.from('%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj 3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj xref 0 4 0000000000 65535 f 0000000009 00000 n 0000000052 00000 n 0000000114 00000 n 0000000221 00000 n trailer<</Size 4/Root 1 0 R>>startxref 298%%EOF');

    // Create actual test resume PDF with proper content
    const resumeContent = `Ahmad Test Candidate
Email: ahmad.test@email.com

EXPERIENCE:
Machine Learning Engineer at Tech Corp (2022-Present)
- Built RAG systems for enterprise knowledge retrieval
- Implemented transformer models for NLP tasks
- Deployed ML models using FastAPI and Docker

PROJECTS:
1. RAG Chatbot - Built retrieval-augmented generation system using LangChain and Pinecone
2. Image Classifier - CNN-based image classification with PyTorch

SKILLS: Python, PyTorch, TensorFlow, LangChain, FastAPI, PostgreSQL, Docker

EDUCATION:
B.S. Computer Science, State University 2022
`;

    // For testing, let's just try to upload and see what happens
    console.log('4. Attempting to create candidate and upload resume...');

    // Click upload zone but we'll skip the actual file upload for now since we don't have a real PDF
    // Instead, let's just test the API directly

    // First create a candidate via API
    const response = await page.evaluate(async () => {
      const res = await fetch('/api/candidates', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: 'Ahmad Test Candidate', email: 'ahmad@test.com' })
      });
      return { status: res.status, data: await res.json() };
    });

    console.log('   API Response:', JSON.stringify(response, null, 2));

    if (response.status === 200 || response.status === 201) {
      const candidateId = response.data?.id;
      console.log('   Candidate created with ID:', candidateId);

      await page.screenshot({ path: 'step4_candidate_created.png', fullPage: true });

      // Now try to create an interview
      const interviewRes = await page.evaluate(async (cId) => {
        const res = await fetch('/api/interviews', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ candidate_id: cId, job_description: 'ML Engineer' })
        });
        return { status: res.status, data: await res.json() };
      }, candidateId);

      console.log('   Interview API Response:', JSON.stringify(interviewRes, null, 2));

      if (interviewRes.data?.id) {
        const interviewId = interviewRes.data.id;
        console.log('   Interview created with ID:', interviewId);

        // Navigate to interview room
        console.log('5. Navigating to interview room...');
        await page.goto(`http://localhost:3000/interview/${interviewId}`, { waitUntil: 'networkidle', timeout: 10000 });
        await page.screenshot({ path: 'step5_interview_room.png', fullPage: true });

        // Wait for WebSocket connection and first question
        console.log('6. Waiting for interview to initialize...');
        await page.waitForTimeout(5000);
        await page.screenshot({ path: 'step6_interview_started.png', fullPage: true });

        // Check for messages
        const messages = await page.$$('.message');
        console.log('   Messages displayed:', messages.length);

        // Try typing an answer
        console.log('7. Submitting a test answer...');
        await page.fill('textarea', 'I have worked on machine learning projects including building RAG systems and NLP models with transformers.');
        await page.click('button:has-text("Send")');
        await page.waitForTimeout(3000);
        await page.screenshot({ path: 'step7_answer_submitted.png', fullPage: true });

        // Check if evaluation appears
        const evalPanel = await page.$('.evaluation-panel');
        if (evalPanel) {
          console.log('   Evaluation panel found!');
        }

        // Submit a few more answers to test flow
        for (let i = 0; i < 3; i++) {
          await page.fill('textarea', 'I used Python, PyTorch, and FastAPI for the project. The RAG system used LangChain for orchestration and Pinecone for vector storage.');
          await page.click('button:has-text("Send")');
          await page.waitForTimeout(4000);
          await page.screenshot({ path: `step8_answer_${i}.png`, fullPage: true });
        }

        // End interview
        console.log('8. Ending interview...');
        await page.click('button:has-text("End Interview")');
        await page.waitForTimeout(3000);
        await page.screenshot({ path: 'step9_interview_ended.png', fullPage: true });

        // Check if redirected to report
        const currentUrl = page.url();
        console.log('   Current URL:', currentUrl);
      }
    }

  } catch (error) {
    console.error('Test error:', error.message);
    await page.screenshot({ path: 'error_screenshot.png', fullPage: true });
  }

  console.log('\n=== Test Complete ===');
  console.log('Screenshots saved in:', __dirname);

  await browser.close();
})();