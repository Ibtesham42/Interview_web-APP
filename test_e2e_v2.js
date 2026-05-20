const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: false, slowMo: 300 });
  const context = await browser.newContext({ viewport: { width: 1400, height: 900 } });
  const page = await context.newPage();

  // Capture console messages
  page.on('console', msg => {
    console.log(`[Browser ${msg.type()}]: ${msg.text()}`);
  });

  page.on('pageerror', err => {
    console.log('[Page Error]:', err.message);
  });

  console.log('=== AI Mock Interview E2E Test ===\n');

  try {
    // Navigate to app
    console.log('1. Opening http://localhost:3000...');
    await page.goto('http://localhost:3000', { waitUntil: 'networkidle', timeout: 15000 });
    await page.screenshot({ path: 'screenshots/e2e_01_home.png', fullPage: true });
    console.log('   Homepage loaded.\n');

    // Create candidate via API
    console.log('2. Creating test candidate via API...');
    const candidateRes = await page.evaluate(async () => {
      const res = await fetch('/api/candidates', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: 'Test Candidate Ahmad', email: 'ahmad@test.com' })
      });
      return res.json();
    });
    console.log('   Candidate:', candidateRes.id);
    await page.screenshot({ path: 'screenshots/e2e_02_candidate.png', fullPage: true });

    // Create interview
    console.log('3. Creating interview...');
    const interviewRes = await page.evaluate(async (cId) => {
      const res = await fetch('/api/interviews', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ candidate_id: cId, job_description: 'ML Engineer' })
      });
      return res.json();
    }, candidateRes.id);
    console.log('   Interview:', interviewRes.id);

    // Navigate to interview room
    console.log('4. Navigating to interview room...');
    await page.goto(`http://localhost:3000/interview/${interviewRes.id}`, { waitUntil: 'domcontentloaded', timeout: 15000 });
    await page.screenshot({ path: 'screenshots/e2e_04_room_loaded.png', fullPage: true });
    console.log('   URL:', page.url());

    // Wait for WebSocket to connect and first question
    console.log('5. Waiting for WebSocket connection (10s)...');
    await page.waitForTimeout(10000);
    await page.screenshot({ path: 'screenshots/e2e_05_after_wait.png', fullPage: true });

    // Check for any elements
    const chatWindow = await page.$('.chat-window');
    console.log('   Chat window found:', !!chatWindow);

    const messages = await page.$$('.message');
    console.log('   Messages count:', messages.length);

    // Try to see what text is visible
    const bodyText = await page.textContent('body');
    console.log('   Body text preview:', bodyText.substring(0, 500));

    // Check phase indicator
    const phaseDots = await page.$$('.phase-dot');
    console.log('   Phase dots:', phaseDots.length);

    // Check loading state
    const loadingEl = await page.$('.loading');
    console.log('   Loading element:', !!loadingEl);

    // Check current question area
    const currentQ = await page.$('.current-question, [class*="current"]');
    if (currentQ) {
      const qText = await currentQ.textContent();
      console.log('   Current question:', qText);
    }

    // Type an answer and submit
    console.log('6. Submitting text answer...');
    const textarea = await page.$('textarea');
    if (textarea) {
      await textarea.fill('I have been working on machine learning projects involving NLP and transformer models. I built a RAG system using LangChain and worked with PyTorch for model training.');
      await page.screenshot({ path: 'screenshots/e2e_06_answer_typed.png', fullPage: true });

      const sendBtn = await page.$('button.btn-primary');
      if (sendBtn) {
        await sendBtn.click();
        await page.waitForTimeout(5000);
        await page.screenshot({ path: 'screenshots/e2e_07_after_send.png', fullPage: true });
      }
    } else {
      console.log('   No textarea found!');
    }

    // Check messages after send
    const newMessages = await page.$$('.message');
    console.log('   Messages after send:', newMessages.length);

    // Try voice button if exists
    const voiceBtn = await page.$('.icon-btn');
    if (voiceBtn) {
      console.log('7. Voice button found - recording feature available');
    }

    // Check for any evaluation panel
    const evalPanel = await page.$('.evaluation-panel');
    console.log('   Evaluation panel:', !!evalPanel);

    // End interview
    const endBtn = await page.$('button.btn-danger');
    if (endBtn) {
      console.log('8. Clicking End Interview...');
      await endBtn.click();
      await page.waitForTimeout(3000);
      await page.screenshot({ path: 'screenshots/e2e_08_ended.png', fullPage: true });
      console.log('   Final URL:', page.url());
    }

  } catch (error) {
    console.error('Test error:', error.message);
    await page.screenshot({ path: 'screenshots/e2e_error.png', fullPage: true });
  }

  console.log('\n=== Test Complete ===');
  console.log('Screenshots in: screenshots/e2e_*.png');

  await browser.close();
})();