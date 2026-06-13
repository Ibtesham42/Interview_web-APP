import { useEffect, useState } from 'react';
import { jobsApi } from '../../services/api';
import { Button } from '../Button';
import type { Job, JobCreatePayload, JobStatus, JobUpdatePayload } from '../../types';

interface JobFormModalProps {
  /** Present = edit an existing job (PATCH); absent = create (POST). */
  job?: Job;
  onClose: () => void;
  onSaved: (job: Job) => void;
}

const STATUS_OPTIONS: { value: JobStatus; label: string }[] = [
  { value: 'draft', label: 'Draft (not visible)' },
  { value: 'open', label: 'Open (accepting applicants)' },
  { value: 'closed', label: 'Closed (archived)' },
];

/** Best-effort slug from a title — the server is authoritative (it rejects a
 * bad shape with a clear 400), this just saves typing on create. */
function slugify(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 60);
}

/**
 * Create / edit a job requisition. Mirrors the recruiter modal pattern
 * (.modal-backdrop / .modal-panel) and the shared form-group classes; the
 * skills field is a comma-separated list mapped to/from the string[] the API
 * uses. On create, the slug auto-fills from the title until the user edits it.
 */
export function JobFormModal({ job, onClose, onSaved }: JobFormModalProps) {
  const isEdit = !!job;
  const [title, setTitle] = useState(job?.title ?? '');
  const [slug, setSlug] = useState(job?.slug ?? '');
  const [slugEdited, setSlugEdited] = useState(isEdit);
  const [description, setDescription] = useState(job?.description ?? '');
  const [employmentType, setEmploymentType] = useState(job?.employment_type ?? '');
  const [location, setLocation] = useState(job?.location ?? '');
  const [skills, setSkills] = useState((job?.required_skills ?? []).join(', '));
  // Advanced interview flow (Phase 3): per-job tuning, stored in interview_config.
  const initialConfig: Record<string, unknown> = job?.interview_config ?? {};
  const [focusAreas, setFocusAreas] = useState(
    Array.isArray(initialConfig.focus_areas)
      ? (initialConfig.focus_areas as unknown[]).map(String).join(', ')
      : '',
  );
  const [instructions, setInstructions] = useState(
    typeof initialConfig.instructions === 'string' ? initialConfig.instructions : '',
  );
  const [status, setStatus] = useState<JobStatus>(job?.status ?? 'draft');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Escape closes — matches the other recruiter modals.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const handleTitleChange = (value: string) => {
    setTitle(value);
    if (!slugEdited) setSlug(slugify(value));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!title.trim() || !slug.trim()) {
      setError('Title and slug are required.');
      return;
    }
    setSaving(true);
    // Build interview_config from the tuning fields. Empty -> {} so the
    // interviewer prompt is unchanged for this job (strictly additive backend).
    const interviewConfig: Record<string, unknown> = {};
    const focus = focusAreas.split(',').map((s) => s.trim()).filter(Boolean);
    if (focus.length) interviewConfig.focus_areas = focus;
    if (instructions.trim()) interviewConfig.instructions = instructions.trim();
    const payload: JobCreatePayload = {
      title: title.trim(),
      slug: slug.trim().toLowerCase(),
      description: description.trim() || undefined,
      employment_type: employmentType.trim() || undefined,
      location: location.trim() || undefined,
      required_skills: skills
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean),
      status,
      interview_config: interviewConfig,
    };
    try {
      const saved = isEdit
        ? await jobsApi.update(job.id, payload as JobUpdatePayload)
        : await jobsApi.create(payload);
      onSaved(saved);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save the job');
      setSaving(false);
    }
  };

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="job-form-title" onClick={onClose}>
      <div className="modal-panel job-form-panel" onClick={(e) => e.stopPropagation()}>
        <h3 id="job-form-title">{isEdit ? 'Edit job' : 'New job'}</h3>
        <form className="job-form" onSubmit={handleSubmit}>
          <div className="form-group">
            <label className="form-label" htmlFor="job-title">Title</label>
            <input
              id="job-title"
              type="text"
              className="form-input"
              value={title}
              onChange={(e) => handleTitleChange(e.target.value)}
              maxLength={120}
              required
              autoFocus
            />
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="job-slug">
              Slug <span className="cell-sub">· used in the apply link</span>
            </label>
            <input
              id="job-slug"
              type="text"
              className="form-input"
              value={slug}
              onChange={(e) => {
                setSlugEdited(true);
                setSlug(e.target.value);
              }}
              pattern="[a-z][a-z0-9\-]*"
              maxLength={60}
              required
            />
            <p className="form-hint">Lowercase letters, digits and hyphens; starts with a letter.</p>
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="job-description">Description</label>
            <textarea
              id="job-description"
              className="form-input"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={5}
            />
          </div>

          <div className="job-form-row">
            <div className="form-group">
              <label className="form-label" htmlFor="job-employment">Employment type</label>
              <input
                id="job-employment"
                type="text"
                className="form-input"
                value={employmentType}
                onChange={(e) => setEmploymentType(e.target.value)}
                placeholder="Full-time"
                maxLength={60}
              />
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="job-location">Location</label>
              <input
                id="job-location"
                type="text"
                className="form-input"
                value={location}
                onChange={(e) => setLocation(e.target.value)}
                placeholder="Remote"
                maxLength={160}
              />
            </div>
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="job-skills">
              Required skills <span className="cell-sub">· comma-separated</span>
            </label>
            <input
              id="job-skills"
              type="text"
              className="form-input"
              value={skills}
              onChange={(e) => setSkills(e.target.value)}
              placeholder="python, fastapi, postgres"
            />
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="job-focus">
              Interview focus areas <span className="cell-sub">· optional, comma-separated</span>
            </label>
            <input
              id="job-focus"
              type="text"
              className="form-input"
              value={focusAreas}
              onChange={(e) => setFocusAreas(e.target.value)}
              placeholder="system design, scalability"
            />
            <p className="form-hint">
              Extra emphasis the AI interviewer weaves in for this role. It adds to
              the standard 5-phase interview — it doesn't replace it.
            </p>
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="job-instructions">
              Interviewer instructions <span className="cell-sub">· optional</span>
            </label>
            <textarea
              id="job-instructions"
              className="form-input"
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
              rows={2}
              maxLength={500}
              placeholder="e.g. Probe trade-offs in their system-design answers."
            />
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="job-status">Status</label>
            <select
              id="job-status"
              className="form-input"
              value={status}
              onChange={(e) => setStatus(e.target.value as JobStatus)}
            >
              {STATUS_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </div>

          {error && <div className="error-message" role="alert">{error}</div>}

          <div className="modal-actions">
            <Button type="button" variant="secondary" onClick={onClose} disabled={saving}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" disabled={saving}>
              {saving ? 'Saving…' : isEdit ? 'Save changes' : 'Create job'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
