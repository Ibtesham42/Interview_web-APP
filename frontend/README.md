# AI Mock Interview - Frontend

React + TypeScript frontend for the AI Mock Interview system.

## Setup

```bash
cd frontend
npm install
npm run dev
```

The frontend runs on http://localhost:3000 and proxies API requests to the backend at http://localhost:8000.

## Features

- Upload candidate resume (PDF)
- Real-time interview via WebSocket
- Text input for answers
- Voice recording (WebSocket audio streaming)
- Live evaluation scores
- Final report with phase-by-phase breakdown

## Routes

- `/` - Home, upload resume
- `/interview/:id` - Interview room
- `/report/:id` - Evaluation report
