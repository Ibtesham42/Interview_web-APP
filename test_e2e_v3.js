const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: false, slowMo: 200 });
  const context = await browser.newContext({ viewport: { width: 1400, height: 900 } });
  const page = await context.newPage();

  page.on('console', msg => {
    console.log(`[Browser ${msg.type()}]: ${msg.text()}`);
  });

  console.log('=== Detailed E2E Test with WS Debug ===\n');

  try {
    // Navigate to app
    console.log('1. Opening homepage...');
    await page.goto('http://localhost:3000', { waitUntil: 'networkidle' });
    await page.screenshot({ path: 'screenshots/e2e_v2_01.png', fullPage: true });

    // Create candidate
    console.log('2. Creating candidate...');
    const candidateRes = await page.evaluate(async () => {
      const res = await fetch('/api/candidates', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: 'John ML Engineer', email: 'john@ml.com' })
      });
      return res.json();
    });
    console.log('   Candidate ID:', candidateRes.id);

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
    console.log('   Interview ID:', interviewRes.id);

    // Navigate and manually connect to WebSocket to debug
    console.log('4. Navigating to interview room...');
    await page.goto(`http://localhost:3000/interview/${interviewRes.id}`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(3000);
    await page.screenshot({ path: 'screenshots/e2e_v2_02.png', fullPage: true });

    // Inject WebSocket client to debug
    console.log('5. Testing WebSocket connection manually...');
    const wsTest = await page.evaluate(async (intId) => {
      return new Promise((resolve) => {
        const ws = new WebSocket('ws://localhost:8000/ws/interview/' + intId);

        let messages = [];
        ws.onopen = () => {
          resolve({ status: 'connected', messages });
        };

        ws.onmessage = (event) => {
          const data = JSON.parse(event.data);
          messages.push(data);
          console.log('WS Message:', JSON.stringify(data));
        };

        ws.onerror = (err) => {
          resolve({ status: 'error', error: err.message });
        };

        setTimeout(() => {
          resolve({ status: 'timeout', messages });
        }, 5000);
      });
    }, interviewRes.id);

    console.log('   WS Test Result:', JSON.stringify(wsTest, null, 2));

    await page.screenshot({ path: 'screenshots/e2e_v2_03.png', fullPage: true });

    // Check the actual page state
    console.log('6. Checking page state...');
    const state = await page.evaluate(() => {
      const chatWindow = document.querySelector('.chat-window');
      const messages = document.querySelectorAll('.message');
      const textarea = document.querySelector('textarea');
      const phaseDots = document.querySelectorAll('.phase-dot');
      const candidateNameEl = document.querySelector('h2');

      return {
        hasChatWindow: !!chatWindow,
        messageCount: messages.length,
        hasTextarea: !!textarea,
        phaseDotCount: phaseDots.length,
        candidateNameText: candidateNameEl ? candidateNameEl.textContent : null,
        bodyTextLength: document.body.textContent.length
      };
    });
    console.log('   Page state:', JSON.stringify(state, null, 2));

    // Try typing and sending
    if (state.hasTextarea) {
      console.log('7. Sending a detailed answer...');
      await page.fill('textarea', 'I have been working as a machine learning engineer for the past 3 years. My main projects include building RAG systems using LangChain and Pinecone, training transformer models for NLP tasks, and deploying ML models using FastAPI and Docker containers.');
      await page.screenshot({ path: 'screenshots/e2e_v2_04.png', fullPage: true });

      await page.click('button.btn-primary');
      await page.waitForTimeout(5000);
      await page.screenshot({ path: 'screenshots/e2e_v2_05.png', fullPage: true });

      // Check messages
      const msgCount = await page.$$eval('.message', els => els.length);
      console.log('   Messages after send:', msgCount);
    }

    // Submit more answers for a real flow
    console.log('8. Submitting more answers to simulate conversation...');
    for (let i = 0; i < 3; i++) {
      const answers = [
        'I chose to use RAG because it provides up-to-date information and allows for efficient knowledge retrieval without fine-tuning.',
        'The main challenge was handling vector similarity search at scale. We used HNSW indexing to improve query performance.',
        'For the transformer architecture, I used self-attention mechanisms and positional encodings. We also implemented layer normalization.'
      ];

      if (state.hasTextarea) {
        await page.fill('textarea', answers[i]);
        await page.click('button.btn-primary');
        await page.waitForTimeout(4000);
        await page.screenshot({ path: `screenshots/e2e_v2_06_${i}.png`, fullPage: true });
      }
    }

    // Check evaluations
    const evalExists = await page.$('.evaluation-panel');
    console.log('9. Evaluation panel exists:', !!evalExists);

    // End interview
    const endBtn = await page.$('button.btn-danger');
    if (endBtn) {
      await endBtn.click();
      await page.waitForTimeout(3000);
      await page.screenshot({ path: 'screenshots/e2e_v2_07_end.png', fullPage: true });
      console.log('   Final URL:', page.url());
    }

  } catch (error) {
    console.error('Error:', error.message);
    await page.screenshot({ path: 'screenshots/e2e_v2_error.png', fullPage: true });
  }

  console.log('\n=== Done ===');
  await browser.close();
})();