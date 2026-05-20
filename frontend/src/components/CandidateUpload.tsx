import { useState, useRef, useCallback, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { candidateApi, interviewApi } from '../services/api';
import { useAuth } from '../contexts/AuthContext';
import { useTilt } from '../hooks/useTilt';
import type { Candidate } from '../types';

const DOMAIN_OPTIONS = [
  { value: 'ml', label: 'Machine Learning' },
  { value: 'nlp', label: 'NLP / LLMs' },
  { value: 'cv', label: 'Computer Vision' },
  { value: 'data_science', label: 'Data Science' },
  { value: 'web_dev', label: 'Web Development' },
  { value: 'mobile', label: 'Mobile Development' },
  { value: 'devops', label: 'DevOps / SRE' },
  { value: 'backend', label: 'Backend Engineering' },
  { value: 'frontend', label: 'Frontend Engineering' },
  { value: 'fullstack', label: 'Full Stack' },
  { value: 'cloud', label: 'Cloud Engineering' },
  { value: 'security', label: 'Security' },
  { value: 'blockchain', label: 'Blockchain' },
  { value: 'game', label: 'Game Development' },
  { value: 'embedded', label: 'Embedded Systems' },
  { value: 'qa', label: 'QA / Testing' },
  { value: 'product', label: 'Product Management' },
  { value: 'design', label: 'UX/UI Design' },
  { value: 'data_eng', label: 'Data Engineering' },
  { value: 'analytics', label: 'Data Analytics' },
  { value: 'research', label: 'Research' },
  { value: 'finance', label: 'Finance' },
  { value: 'legal', label: 'Legal Tech' },
  { value: 'healthcare', label: 'Healthcare Tech' },
  { value: 'marketing', label: 'Marketing Tech' },
  { value: 'general', label: 'General Software' },
];

const ALLOWED_EXT = ['.pdf', '.doc', '.docx', '.txt', '.md'];

export function CandidateUpload() {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [field, setField] = useState('general');
  const [file, setFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [candidate, setCandidate] = useState<Candidate | null>(null);
  const [resumeParsed, setResumeParsed] = useState(false);
  const [starting, setStarting] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const { user, profile } = useAuth();
  const tilt = useTilt(4);

  // Pre-fill the candidate's identity from the signed-in account.
  useEffect(() => {
    if (profile?.full_name) setName((prev) => prev || profile.full_name || '');
    if (user?.email) setEmail((prev) => prev || user.email || '');
  }, [profile, user]);

  const getFieldLabel = (value: string) =>
    DOMAIN_OPTIONS.find((f) => f.value === value)?.label || value;

  const handleFileSelect = useCallback((selectedFile: File) => {
    const ext = `.${selectedFile.name.split('.').pop()?.toLowerCase() ?? ''}`;
    if (!ALLOWED_EXT.includes(ext)) {
      setError('Unsupported file type. Upload a PDF, DOC, DOCX, TXT or MD file.');
      return;
    }
    setFile(selectedFile);
    setError(null);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const dropped = e.dataTransfer.files[0];
      if (dropped) handleFileSelect(dropped);
    },
    [handleFileSelect],
  );

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) {
      setError('Please enter your name.');
      return;
    }
    if (!file) {
      setError('Please upload a document to continue.');
      return;
    }

    setUploading(true);
    setError(null);

    try {
      const newCandidate = await candidateApi.create({
        name: name.trim(),
        email: email.trim() || undefined,
        field_specialization: field,
      });
      setCandidate(newCandidate);

      await candidateApi.uploadResume(newCandidate.id, file);
      setResumeParsed(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not process your document.');
    } finally {
      setUploading(false);
    }
  };

  const startInterview = async () => {
    if (!candidate) return;
    setStarting(true);
    setError(null);
    try {
      const interview = await interviewApi.create({
        candidate_id: candidate.id,
        job_description: getFieldLabel(field),
      });
      navigate(`/interview/${interview.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start the interview.');
      setStarting(false);
    }
  };

  return (
    <div className="onboard-card">
      <div className="onboard-head">
        <span className="onboard-eyebrow">New session</span>
        <h2 className="onboard-title">Set up your interview</h2>
        <p className="onboard-sub">
          Upload your resume and we'll tailor every question to your experience.
        </p>
      </div>

      {!resumeParsed && (
        <form onSubmit={handleSubmit} className="onboard-form">
          <div className="field-grid">
            <div className="form-group">
              <label className="form-label" htmlFor="cand-name">Full name</label>
              <input
                id="cand-name"
                type="text"
                className="form-input"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Your full name"
                required
              />
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="cand-email">Email</label>
              <input
                id="cand-email"
                type="email"
                className="form-input"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
              />
            </div>
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="cand-field">Interview focus</label>
            <select
              id="cand-field"
              className="form-input"
              value={field}
              onChange={(e) => setField(e.target.value)}
              required
            >
              {DOMAIN_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </div>

          <div className="form-group">
            <label className="form-label">Your document</label>
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.doc,.docx,.txt,.md"
              hidden
              onChange={(e) => e.target.files?.[0] && handleFileSelect(e.target.files[0])}
            />
            <div
              ref={tilt.ref}
              className={`upload-zone${file ? ' has-file' : ''}${dragOver ? ' dragover' : ''}`}
              onClick={() => fileInputRef.current?.click()}
              onDrop={handleDrop}
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onMouseMove={tilt.onMouseMove}
              onMouseLeave={tilt.onMouseLeave}
            >
              {file ? (
                <div className="upload-filled">
                  <div className="upload-icon success">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <polyline points="20 6 9 17 4 12" />
                    </svg>
                  </div>
                  <div className="upload-meta">
                    <h4>{file.name}</h4>
                    <p>Click or drop a file to replace</p>
                  </div>
                </div>
              ) : (
                <>
                  <div className="upload-icon">
                    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                      <polyline points="14 2 14 8 20 8" />
                      <line x1="12" y1="18" x2="12" y2="12" />
                      <line x1="9" y1="15" x2="15" y2="15" />
                    </svg>
                  </div>
                  <h4>Drop your document here</h4>
                  <p>PDF, DOC, DOCX, TXT or MD — or click to browse</p>
                </>
              )}
            </div>
          </div>

          {error && <div className="error-message">{error}</div>}

          <button
            type="submit"
            className="btn btn-primary btn-lg onboard-submit"
            disabled={uploading}
          >
            {uploading ? (
              <>
                <span className="spinner" style={{ width: '16px', height: '16px' }} />
                Analyzing your document…
              </>
            ) : (
              'Begin Interview'
            )}
          </button>
        </form>
      )}

      {candidate && resumeParsed && (
        <div className="onboard-ready">
          <div className="onboard-ready-icon">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <polyline points="20 6 9 17 4 12" />
            </svg>
          </div>
          <h3>You're all set{name ? `, ${name.split(' ')[0]}` : ''}</h3>
          <p>Resume analyzed · {getFieldLabel(field)} interview</p>
          {error && <div className="error-message">{error}</div>}
          <button
            className="btn btn-primary btn-lg"
            onClick={startInterview}
            disabled={starting}
            style={{ width: '100%' }}
          >
            {starting ? 'Starting…' : 'Start Interview'}
          </button>
        </div>
      )}
    </div>
  );
}
