-- Supabase Database Schema for AI Mock Interview Agent
-- Run this SQL in your Supabase SQL Editor

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Candidates table
CREATE TABLE candidates (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) UNIQUE,
    name VARCHAR(255) NOT NULL,
    resume_text TEXT,
    resume_sections JSONB DEFAULT '{}',
    field_specialization VARCHAR(50) DEFAULT 'general',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Interviews table
CREATE TABLE interviews (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    candidate_id UUID REFERENCES candidates(id) ON DELETE CASCADE,
    job_description TEXT,
    status VARCHAR(50) DEFAULT 'phase_1',
    current_phase INT DEFAULT 1,
    conversation_history JSONB DEFAULT '[]',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE
);

-- Evaluations table
CREATE TABLE evaluations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    interview_id UUID REFERENCES interviews(id) ON DELETE CASCADE,
    phase INT NOT NULL,
    depth_score FLOAT,
    accuracy_score FLOAT,
    clarity_score FLOAT,
    follow_up_score FLOAT,
    overall_score FLOAT,
    details JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ML Questions table with vector embedding support
CREATE TABLE ml_questions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    category VARCHAR(100) NOT NULL,
    question TEXT NOT NULL,
    answer TEXT,
    embedding VECTOR(384)
);

-- Index for vector similarity search
CREATE INDEX idx_ml_questions_embedding ON ml_questions USING ivfflat (embedding vector_cosine_ops);

-- Indexes for common queries
CREATE INDEX idx_candidates_email ON candidates(email);
CREATE INDEX idx_interviews_candidate ON interviews(candidate_id);
CREATE INDEX idx_interviews_status ON interviews(status);
CREATE INDEX idx_evaluations_interview ON evaluations(interview_id);
CREATE INDEX idx_ml_questions_category ON ml_questions(category);

-- Row Level Security (RLS) - Enable for production
ALTER TABLE candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE interviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE evaluations ENABLE ROW LEVEL SECURITY;
ALTER TABLE ml_questions ENABLE ROW LEVEL SECURITY;

-- RLS Policies (allow all for now - restrict in production)
CREATE POLICY "Allow all candidates" ON candidates FOR ALL USING (true);
CREATE POLICY "Allow all interviews" ON interviews FOR ALL USING (true);
CREATE POLICY "Allow all evaluations" ON evaluations FOR ALL USING (true);
CREATE POLICY "Allow all ml_questions" ON ml_questions FOR ALL USING (true);
