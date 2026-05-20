const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: false, slowMo: 100 });
  const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
  const page = await context.newPage();

  page.on('console', msg => console.log(`[Browser]: ${msg.text()}`));

  console.log('=== AI Mock Interview Full E2E Test ===\n');

  let testCandidateId = null;
  let testInterviewId = null;

  try {
    // STEP 1: Home page loads
    console.log('STEP 1: Loading homepage...');
    await page.goto('http://localhost:3000', { waitUntil: 'networkidle' });
    await page.screenshot({ path: 'screenshots/full_01_home.png', fullPage: true });

    // STEP 2: Create candidate
    console.log('\nSTEP 2: Creating candidate via API...');
    const candidateRes = await page.evaluate(async () => {
      const res = await fetch('/api/candidates', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: 'Sarah Chen ML Engineer', email: 'sarah@mltest.com' })
      });
      return res.json();
    });
    testCandidateId = candidateRes.id;
    console.log('   Created candidate:', testCandidateId);
    await page.screenshot({ path: 'screenshots/full_02_candidate.png', fullPage: true });

    // STEP 3: Create interview
    console.log('\nSTEP 3: Creating interview...');
    const interviewRes = await page.evaluate(async (cId) => {
      const res = await fetch('/api/interviews', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ candidate_id: cId, job_description: 'Senior ML Engineer' })
      });
      return res.json();
    }, testCandidateId);
    testInterviewId = interviewRes.id;
    console.log('   Created interview:', testInterviewId);

    // STEP 4: Navigate to interview room
    console.log('\nSTEP 4: Opening interview room...');
    await page.goto(`http://localhost:3000/interview/${testInterviewId}`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2000);
    await page.screenshot({ path: 'screenshots/full_04_room.png', fullPage: true });

    // STEP 5: Manually test WebSocket connection to ensure it works
    console.log('\nSTEP 5: Testing WebSocket manually and capturing all messages...');
    const wsResult = await page.evaluate(async (intId) => {
      return new Promise((resolve) => {
        const messages = [];
        const ws = new WebSocket('ws://localhost:8000/ws/interview/' + intId);

        ws.onopen = () => {
          messages.push({ type: 'ws_open' });
          console.log('WS Opened');
        };

        ws.onmessage = (event) => {
          const data = JSON.parse(event.data);
          messages.push(data);
          console.log('WS Message:', JSON.stringify(data).substring(0, 200));

          // If we got a question, send an answer after a short delay
          if (data.type === 'question') {
            setTimeout(() => {
              console.log('Sending answer to question...');
              ws.send(JSON.stringify({ type: 'answer', content: 'I have been working on machine learning projects for the past 4 years. I have experience with NLP, computer vision, and building ML systems in production.' }));
            }, 1000);
          }
        };

        ws.onerror = (err) => {
          messages.push({ type: 'ws_error', error: err.message });
          console.log('WS Error:', err.message);
        };

        ws.onclose = (code, reason) => {
          messages.push({ type: 'ws_close', code, reason: reason?.toString() });
          console.log('WS Close:', code, reason?.toString());
        };

        // Wait 15 seconds then resolve with all messages
        setTimeout(() => {
          console.log('Resolving with', messages.length, 'messages');
          resolve({ messageCount: messages.length, messages });
        }, 15000);
      });
    }, testInterviewId);

    console.log('\n   WebSocket result:', JSON.stringify(wsResult, null, 2));

    await page.waitForTimeout(5000);
    await page.screenshot({ path: 'screenshots/full_05_ws_test.png', fullPage: true });

    // STEP 6: Check page state and try to submit answer
    console.log('\nSTEP 6: Checking page state...');
    const pageState = await page.evaluate(() => {
      return {
        hasChatWindow: !!document.querySelector('.chat-window'),
        messageCount: document.querySelectorAll('.message').length,
        hasTextarea: !!document.querySelector('textarea'),
        textareaValue: document.querySelector('textarea')?.value || '',
        hasCurrentQuestion: !!document.querySelector('[class*="current"]'),
        phaseDots: document.querySelectorAll('.phase-dot').length,
        bodyText: document.body.textContent.substring(0, 300)
      };
    });
    console.log('   Page state:', JSON.stringify(pageState, null, 2));

    // If there's a textarea, try submitting an answer
    if (pageState.hasTextarea) {
      console.log('\nSTEP 7: Submitting answer via UI...');
      await page.fill('textarea', 'I have experience with NLP transformers, building RAG systems with LangChain, and deploying ML models using FastAPI and Docker.');
      await page.screenshot({ path: 'screenshots/full_07_answer.png', fullPage: true });

      const sendBtn = await page.$('button.btn-primary');
      if (sendBtn) {
        await sendBtn.click();
        console.log('   Clicked send button');
        await page.waitForTimeout(5000);
        await page.screenshot({ path: 'screenshots/full_07_after_send.png', fullPage: true });
      }
    }

    // STEP 8: Check messages after interaction
    const afterState = await page.evaluate(() => {
      const msgs = document.querySelectorAll('.message');
      return {
        messageCount: msgs.length,
        messages: Array.from(msgs).map(m => m.textContent?.substring(0, 100))
      };
    });
    console.log('\nSTEP 8: Messages after interaction:', JSON.stringify(afterState, null, 2));

    // STEP 9: Continue with more answers to simulate full flow
    console.log('\nSTEP 9: Sending more answers...');
    const answers = [
      'For the RAG system, we used Pinecone for vector storage and LangChain for orchestration. The main challenge was optimizing retrieval latency.',
      'We implemented self-attention mechanisms and used BERT-style architecture for the transformer model.',
      'I chose this approach because it provided better context understanding compared to previous methods.'
    ];

    for (let i = 0; i < answers.length; i++) {
      const textarea = await page.$('textarea');
      if (textarea) {
        await textarea.fill(answers[i]);
        await page.click('button.btn-primary');
        console.log(`   Sent answer ${i + 1}`);
        await page.waitForTimeout(4000);
        await page.screenshot({ path: `screenshots/full_09_${i}.png`, fullPage: true });
      }
    }

    // STEP 10: Check for evaluation panel
    console.log('\nSTEP 10: Checking for evaluation...');
    const evalPanel = await page.$('.evaluation-panel');
    if (evalPanel) {
      console.log('   Evaluation panel found!');
      const evalText = await evalPanel.textContent();
      console.log('   Eval:', evalText?.substring(0, 200));
    }

    // STEP 11: Check phase progression
    const phaseInfo = await page.evaluate(() => {
      const dots = document.querySelectorAll('.phase-dot');
      const activeDot = document.querySelector('.phase-dot.active');
      const completedDots = document.querySelectorAll('.phase-dot.completed');
      return {
        totalDots: dots.length,
        activeDotIndex: Array.from(dots).indexOf(activeDot),
        completedCount: completedDots.length
      };
    });
    console.log('\nSTEP 11: Phase info:', JSON.stringify(phaseInfo, null, 2));

    // STEP 12: End interview
    console.log('\nSTEP 12: Ending interview...');
    const endBtn = await page.$('button.btn-danger');
    if (endBtn) {
      await endBtn.click();
      await page.waitForTimeout(3000);
      await page.screenshot({ path: 'screenshots/full_12_end.png', fullPage: true });
      console.log('   Final URL:', page.url());
    }

    console.log('\n=== E2E Test Complete ===');
    console.log('Test candidate ID:', testCandidateId);
    console.log('Test interview ID:', testInterviewId);

  } catch (error) {
    console.error('\nERROR:', error.message);
    await page.screenshot({ path: 'screenshots/full_error.png', fullPage: true });
  }

  await browser.close();
})();