from fastapi import WebSocket, WebSocketDisconnect
from typing import Dict, Optional
import base64
import json
import re

from uuid import UUID


class InterviewConnectionManager:
    """Manage WebSocket connections for active interviews."""

    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.orchestrators: Dict[str, "InterviewOrchestrator"] = {}
        self._voice_service = None
        self._stt_service = None
        self._voice_analyzer = None
        self._question_retriever = None

    @property
    def voice_service(self):
        if self._voice_service is None:
            from app.services.voice_service import VoiceService
            self._voice_service = VoiceService()
        return self._voice_service

    @property
    def stt_service(self):
        if self._stt_service is None:
            from app.services.voice_service import SpeechToTextService
            self._stt_service = SpeechToTextService()
        return self._stt_service

    @property
    def voice_analyzer(self):
        if self._voice_analyzer is None:
            from app.services.voice_service import VoiceAnalyzer
            self._voice_analyzer = VoiceAnalyzer()
        return self._voice_analyzer

    @property
    def question_retriever(self):
        if self._question_retriever is None:
            from app.services.question_retriever import MLQuestionRetriever
            self._question_retriever = MLQuestionRetriever()
        return self._question_retriever

    async def connect(self, interview_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[interview_id] = websocket

    def disconnect(self, interview_id: str):
        if interview_id in self.active_connections:
            del self.active_connections[interview_id]
        if interview_id in self.orchestrators:
            del self.orchestrators[interview_id]

    async def send_text(self, interview_id: str, message: str):
        if interview_id in self.active_connections:
            await self.active_connections[interview_id].send_json({
                "type": "text",
                "content": message
            })

    async def send_audio(self, interview_id: str, audio_bytes: bytes):
        if interview_id in self.active_connections:
            await self.active_connections[interview_id].send_json({
                "type": "audio",
                "content": base64.b64encode(audio_bytes).decode()
            })

    async def send_phase_update(self, interview_id: str, phase: int, status: str):
        if interview_id in self.active_connections:
            await self.active_connections[interview_id].send_json({
                "type": "phase_update",
                "phase": phase,
                "status": status
            })

    async def send_evaluation(self, interview_id: str, evaluation: dict):
        if interview_id in self.active_connections:
            await self.active_connections[interview_id].send_json({
                "type": "evaluation",
                "data": evaluation
            })

    async def send_empathy_nudge(self, interview_id: str, message: str):
        if interview_id in self.active_connections:
            await self.active_connections[interview_id].send_json({
                "type": "empathy_nudge",
                "content": message
            })


manager = InterviewConnectionManager()


async def send_question_audio(websocket: WebSocket, mgr: InterviewConnectionManager, text: str):
    """Generate TTS for a question and ALWAYS emit an `audio` frame.

    The client uses the audio frame as the signal that the interviewer is
    speaking. Emitting an empty frame on TTS failure keeps the client's turn
    state machine deterministic instead of leaving it waiting indefinitely.
    """
    audio_b64 = ""
    try:
        audio = await mgr.voice_service.text_to_speech(text)
        if audio:
            audio_b64 = base64.b64encode(audio).decode()
    except Exception as e:
        print(f"[WS] TTS generation failed: {e}")
    try:
        await websocket.send_json({"type": "audio", "content": audio_b64})
    except Exception:
        pass


def save_evaluation(supabase, eval_data: dict) -> bool:
    """Insert an evaluation row, tolerating live-schema drift.

    If the `evaluations` table is missing an optional score column, that column
    is dropped and the insert retried. The complete evaluation is always kept
    in the `details` JSONB column, so dropping a flattened score column is
    lossless for report generation.
    """
    data = dict(eval_data)
    for _ in range(6):
        try:
            supabase.table("evaluations").insert(data).execute()
            return True
        except Exception as e:
            match = re.search(r"Could not find the '([^']+)' column", str(e))
            if match and match.group(1) in data:
                data.pop(match.group(1), None)
                continue
            print(f"[WS] Evaluation save failed: {e}")
            return False
    return False


def _authenticate_ws_token(supabase, token: str):
    """Resolve the Supabase user from a WebSocket `token` query param.

    Returns the user object, or None if the token is missing/invalid. Mirrors
    `app.auth.get_current_user` but returns None instead of raising, since a
    WebSocket rejects with a close code rather than an HTTP error.
    """
    if not token:
        return None
    try:
        response = supabase.auth.get_user(token)
    except Exception:
        return None
    user = getattr(response, "user", None)
    if user is None or not getattr(user, "id", None):
        return None
    return user


async def interview_websocket(websocket: WebSocket, interview_id: str):
    """WebSocket endpoint for real-time interview session."""
    from app.supabase_client import get_supabase
    from app.services.interview_orchestrator import InterviewOrchestrator
    from app.services.integrity_monitor import IntegrityMonitor

    supabase = get_supabase()

    # --- Auth gate -------------------------------------------------------
    # Validate the Supabase JWT and interview ownership BEFORE accepting the
    # socket. This is a gate in front of the existing realtime flow, not a
    # change to it; closing before accept() cleanly rejects the handshake.
    user = _authenticate_ws_token(supabase, websocket.query_params.get("token", ""))
    if user is None:
        await websocket.close(code=4401)  # unauthorized
        return

    try:
        interview_result = (
            supabase.table("interviews").select("*").eq("id", interview_id).execute()
        )
    except Exception:
        await websocket.close(code=1011)  # internal error
        return

    if not interview_result.data:
        await websocket.close(code=4404)  # interview not found
        return

    interview = interview_result.data[0]
    owner_id = interview.get("user_id")
    if owner_id is not None and owner_id != user.id:
        await websocket.close(code=4403)  # not the caller's interview
        return

    # --- Accept and run the interview (existing flow below, unchanged) ---
    await manager.connect(interview_id, websocket)

    try:
        candidate_result = supabase.table("candidates").select("*").eq("id", interview["candidate_id"]).execute()

        if not candidate_result.data:
            await websocket.send_json({"type": "error", "message": "Candidate not found"})
            return

        candidate = candidate_result.data[0]

        # Create orchestrator with candidate data for personalized questions
        orchestrator = InterviewOrchestrator(UUID(interview_id), candidate_data=candidate)
        manager.orchestrators[interview_id] = orchestrator

        # Integrity monitor — sibling to the orchestrator, NOT baked into it
        # (the orchestrator already owns enough state). Lives for the WS
        # lifetime; dies with the interview per ADR 0002.
        integrity = IntegrityMonitor(UUID(interview_id), str(user.id))

        # Send initialization data
        await websocket.send_json({
            "type": "init",
            "candidate_name": candidate["name"],
            "candidate_field": candidate.get("field_specialization", "ml"),
            "current_phase": orchestrator.current_phase,
            "resume_sections": candidate.get("resume_sections", {})
        })

        # Generate and send first question
        first_question = await orchestrator.generate_question()
        await websocket.send_json({
            "type": "question",
            "content": first_question,
            "phase": orchestrator.current_phase
        })

        # Always emit an audio frame so the client has a deterministic
        # "interviewer is speaking" signal, even if TTS generation fails.
        await send_question_audio(websocket, manager, first_question)

        # Main conversation loop
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "")
            print(f"[DEBUG WS] Received message type: {msg_type}")

            if msg_type == "answer":
                answer_text = data["content"]

                # Add user answer to conversation history
                orchestrator.add_message("user", answer_text)

                # Check if candidate wants to end the interview
                if orchestrator.should_end_interview(answer_text):
                    # Save any pending evaluation first
                    if len(orchestrator.conversation_history) >= 2:
                        last_q = orchestrator.conversation_history[-2].get("content", "")
                        try:
                            eval_result = await orchestrator.evaluate_answer(
                                last_q, answer_text, orchestrator.current_phase
                            )
                            save_evaluation(supabase, {
                                "interview_id": interview_id,
                                "phase": orchestrator.current_phase,
                                "depth_score": eval_result.get("depth", eval_result.get("correctness", eval_result.get("vision", 0))),
                                "accuracy_score": eval_result.get("correctness", eval_result.get("completeness", 0)),
                                "clarity_score": eval_result.get("clarity", 0),
                                "follow_up_score": eval_result.get("layer", 0),
                                "overall_score": sum(v for v in eval_result.values() if isinstance(v, (int, float))) / max(1, len([v for v in eval_result.values() if isinstance(v, (int, float))])),
                                "details": eval_result
                            })
                        except Exception:
                            pass

                    # End the interview
                    try:
                        supabase.table("interviews").update({
                            "status": "completed",
                            "completed_at": "now()"
                        }).eq("id", interview_id).execute()
                    except Exception:
                        pass

                    await websocket.send_json({"type": "interview_ended"})
                    break

                question_text = ""
                if len(orchestrator.conversation_history) >= 2:
                    question_text = orchestrator.conversation_history[-2].get("content", "")

                evaluation = await orchestrator.evaluate_answer(
                    question_text,
                    answer_text,
                    orchestrator.current_phase
                )

                # Track response count
                orchestrator._total_responses += 1

                # Save evaluation to database
                # Note: clarity_score column may not exist in older schemas
                eval_data = {
                    "interview_id": interview_id,
                    "phase": orchestrator.current_phase,
                    "depth_score": evaluation.get("depth", evaluation.get("correctness", evaluation.get("vision", evaluation.get("relevance", 0)))),
                    "accuracy_score": evaluation.get("correctness", evaluation.get("completeness", evaluation.get("specificity", 0))),
                    "overall_score": sum(v for v in evaluation.values() if isinstance(v, (int, float))) / max(1, len([v for v in evaluation.values() if isinstance(v, (int, float))])),
                    "details": evaluation
                }

                # follow_up_score now records the Matryoshka layer the answer
                # sat at (informational; scoring reads `layer` from details).
                if orchestrator.current_phase in [2, 3]:
                    eval_data["follow_up_score"] = evaluation.get("layer", 0)

                # Try to add clarity_score if it exists in the schema
                if "clarity" in evaluation:
                    eval_data["clarity_score"] = evaluation.get("clarity", 0)

                save_evaluation(supabase, eval_data)

                # The Matryoshka layer is internal-only — strip it from the
                # client-facing evaluation message. It is still persisted in
                # `details` for scoring (ADR 0001).
                await manager.send_evaluation(
                    interview_id,
                    {k: v for k, v in evaluation.items() if k != "layer"},
                )

                # Check phase transition
                should_advance = orchestrator.advance_phase_if_ready(evaluation)
                if should_advance and not orchestrator.is_complete():
                    new_phase = orchestrator.advance_phase()
                    await manager.send_phase_update(interview_id, new_phase, f"phase_{new_phase}")

                # Check if interview should end naturally
                if orchestrator._final_question_asked:
                    # Interview complete after final question
                    try:
                        supabase.table("interviews").update({
                            "status": "completed",
                            "completed_at": "now()"
                        }).eq("id", interview_id).execute()
                    except Exception:
                        pass
                    await websocket.send_json({"type": "interview_ended"})
                    break

                # Generate next question
                next_question = await orchestrator.generate_question(answer_text)

                # Check if interview ended (final question marker)
                if next_question == "[Interview Complete]":
                    try:
                        supabase.table("interviews").update({
                            "status": "completed",
                            "completed_at": "now()"
                        }).eq("id", interview_id).execute()
                    except Exception:
                        pass
                    await websocket.send_json({"type": "interview_ended"})
                    break

                await websocket.send_json({
                    "type": "question",
                    "content": next_question,
                    "phase": orchestrator.current_phase
                })

                # Always emit an audio frame (empty content if TTS fails)
                await send_question_audio(websocket, manager, next_question)

            elif msg_type == "voice":
                # Handle voice input (speech-to-text)
                audio_data = data.get("audio", "")
                duration = data.get("duration", 0)

                if audio_data:
                    try:
                        audio_bytes = base64.b64decode(audio_data)
                        transcript = await manager.stt_service.transcribe_audio(audio_bytes)

                        # Analyze pace if duration provided
                        pace_analysis = None
                        if duration > 0:
                            pace_analysis = await manager.voice_analyzer.analyze_pace(transcript, duration)

                            # Send empathy nudge if speaking too fast
                            if pace_analysis.get("is_too_fast") and pace_analysis.get("recommendation"):
                                nudge = await manager.voice_analyzer.generate_empathy_nudge(pace_analysis)
                                if nudge:
                                    await manager.send_empathy_nudge(interview_id, nudge)

                        # The user's turn is recorded once — by the `answer`
                        # handler — to avoid duplicate conversation history
                        # entries. This handler only returns the transcript.
                        await websocket.send_json({
                            "type": "voice_transcript",
                            "transcript": transcript,
                            "pace": pace_analysis if duration > 0 else None
                        })
                    except Exception as e:
                        print(f"[WS] Voice transcription error: {e}")
                        await websocket.send_json({
                            "type": "voice_error",
                            "message": "Transcription failed. Please record your answer again."
                        })

            elif msg_type == "analyze":
                # Analyze last response for pace/sentiment
                text = data.get("text", "")
                duration = data.get("duration", 0)

                if text and duration > 0:
                    pace_analysis = await manager.voice_analyzer.analyze_pace(text, duration)
                    sentiment = await manager.voice_analyzer.analyze_sentiment_hint(text)

                    await websocket.send_json({
                        "type": "analysis_result",
                        "pace": pace_analysis,
                        "sentiment": sentiment
                    })

            elif msg_type == "integrity_event":
                # Out-of-band integrity signal from the client (tab switch,
                # camera lost, etc.). Persists the event, counts the warning,
                # and at the threshold (3 by default) terminates the interview
                # via the existing interview_ended path. Does NOT interleave
                # with the question/answer turn — it is a parallel concern.
                event_type = data.get("event_type", "unknown")
                metadata = data.get("metadata") or {}
                result = integrity.record_event(event_type, metadata)
                await websocket.send_json({
                    "type": "integrity_warning",
                    "event_type": result["event_type"],
                    "severity": result["severity"],
                    "count": result["count"],
                    "max": result["max"],
                    "terminate": result["terminate"],
                })
                if result["terminate"]:
                    integrity.mark_terminated()
                    await websocket.send_json({
                        "type": "interview_ended",
                        "reason": "integrity_terminated",
                    })
                    break

            elif msg_type == "end_interview":
                # Complete the interview
                try:
                    supabase.table("interviews").update({
                        "status": "completed",
                        "completed_at": "now()"
                    }).eq("id", interview_id).execute()
                except Exception:
                    pass

                await websocket.send_json({"type": "interview_ended"})
                break

    except WebSocketDisconnect:
        manager.disconnect(interview_id)
    except Exception as e:
        print(f"[WS] Interview session error: {e}")
        try:
            await websocket.send_json({
                "type": "error",
                "message": "Something went wrong on the server. Please restart the interview.",
            })
        except Exception:
            pass
        manager.disconnect(interview_id)
