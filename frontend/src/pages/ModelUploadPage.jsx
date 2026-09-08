import React, { useState, useEffect } from 'react';

const API_BASE = '';

const FileField = ({ label, required, onChange }) => (
  <div
    className="file-drop"
    style={{ borderColor: required ? 'rgba(77,166,255,.4)' : undefined }}
  >
    <label className="form-label" style={{ color: required ? 'var(--blue)' : 'var(--text2)', marginBottom: '8px' }}>
      {required && '* '}{label}
    </label>
    <input
      type="file"
      onChange={onChange}
      style={{ fontSize: '13px', color: 'var(--text2)', width: '100%' }}
    />
  </div>
);

const ModelUploadPage = () => {
  const [models, setModels] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [file, setFile] = useState(null);
  const [scalerFile, setScalerFile] = useState(null);
  const [leFile, setLeFile] = useState(null);
  const [modelName, setModelName] = useState('');
  const [description, setDescription] = useState('');
  const [isUploading, setIsUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState(null);

  const fetchModels = async () => {
    setIsLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/models`);
      const data = await res.json();
      if (Array.isArray(data)) setModels(data);
    } catch (err) {
      console.error('Failed to fetch models', err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => { fetchModels(); }, []);

  const handleUpload = async (e) => {
    e.preventDefault();
    if (!file) { setUploadStatus({ type: 'error', msg: 'Please select a main model file.' }); return; }

    setIsUploading(true);
    setUploadStatus(null);

    const fd = new FormData();
    fd.append('file', file);
    if (scalerFile) fd.append('scaler', scalerFile);
    if (leFile) fd.append('le', leFile);
    fd.append('name', modelName || file.name);
    fd.append('description', description);

    try {
      const res = await fetch(`${API_BASE}/api/models/upload`, { method: 'POST', body: fd });
      const data = await res.json();
      if (res.ok && data.ok) {
        setUploadStatus({ type: 'success', msg: 'Model uploaded successfully!' });
        setFile(null); setScalerFile(null); setLeFile(null);
        setModelName(''); setDescription('');
        fetchModels();
      } else {
        setUploadStatus({ type: 'error', msg: data.error || 'Upload failed.' });
      }
    } catch (err) {
      setUploadStatus({ type: 'error', msg: `Upload error: ${err.message}` });
    } finally {
      setIsUploading(false);
    }
  };

  const handleSetActive = async (id) => {
    try {
      const res = await fetch(`${API_BASE}/api/models/active`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id }),
      });
      const data = await res.json();
      if (res.ok && data.ok) fetchModels();
      else alert('Failed: ' + data.error);
    } catch (err) {
      alert('Error: ' + err.message);
    }
  };

  return (
    <div
      className="page-container"
      style={{ padding: '40px 28px', maxWidth: '1040px', margin: '0 auto', display: 'flex', gap: '32px', flexWrap: 'wrap' }}
    >
      {/* ── Upload Section ── */}
      <div style={{ flex: '1 1 380px' }}>
        <h2 className="section-title">Upload ML Model</h2>
        <p className="section-sub" style={{ marginTop: '6px', marginBottom: '24px' }}>
          Upload a trained model (.pkl, .h5) along with its scaler and label encoder files.
        </p>

        <div className="card" style={{ padding: '24px' }}>
          <form onSubmit={handleUpload} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>

            <div>
              <label className="form-label">Model Name (optional)</label>
              <input
                type="text"
                className="form-input"
                value={modelName}
                onChange={(e) => setModelName(e.target.value)}
                placeholder="e.g. LSTM V2"
              />
            </div>

            <div>
              <label className="form-label">Description</label>
              <textarea
                className="form-input form-textarea"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Training data details, performance metrics…"
                rows={3}
              />
            </div>

            <FileField label="Main Model File (.pkl)" required onChange={(e) => e.target.files[0] && setFile(e.target.files[0])} />
            <FileField label="Scaler File (.pkl) — optional" onChange={(e) => e.target.files[0] && setScalerFile(e.target.files[0])} />
            <FileField label="Label Encoder (.pkl) — optional" onChange={(e) => e.target.files[0] && setLeFile(e.target.files[0])} />

            {uploadStatus && (
              <div style={{
                padding: '12px 14px',
                borderRadius: '8px',
                fontSize: '13px',
                background: uploadStatus.type === 'error' ? 'var(--red-dim)' : 'var(--green-dim)',
                color: uploadStatus.type === 'error' ? 'var(--red)' : 'var(--green)',
                borderLeft: `3px solid ${uploadStatus.type === 'error' ? 'var(--red)' : 'var(--green)'}`,
              }}>
                {uploadStatus.msg}
              </div>
            )}

            <button
              type="submit"
              className="deploy-btn"
              disabled={isUploading || !file}
              style={{ marginTop: '4px' }}
            >
              {isUploading ? 'Uploading…' : 'Upload Model'}
            </button>
          </form>
        </div>
      </div>

      {/* ── Models List ── */}
      <div style={{ flex: '1 1 420px' }}>
        <h2 className="section-title">Available Models</h2>
        <p className="section-sub" style={{ marginTop: '6px', marginBottom: '24px' }}>
          Select the active model used by the Ryu Controller for traffic classification.
        </p>

        {isLoading ? (
          <div style={{ padding: '48px', textAlign: 'center', color: 'var(--muted)', fontFamily: 'var(--font-mono)', fontSize: '13px' }}>
            Loading…
          </div>
        ) : models.length === 0 ? (
          <div className="card" style={{ padding: '48px', textAlign: 'center' }}>
            <div style={{ fontSize: '32px', marginBottom: '12px' }}>📭</div>
            <div style={{ color: 'var(--muted)', fontSize: '13px' }}>No models uploaded yet</div>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {models.map((model) => (
              <div key={model.id} className={`model-card${model.is_active ? ' active' : ''}`}>
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '4px' }}>
                    <span style={{ fontSize: '15px', fontWeight: 600 }}>{model.name}</span>
                    {model.is_active && <span className="badge badge-green">ACTIVE</span>}
                  </div>
                  <div style={{ fontSize: '11px', color: 'var(--muted)', fontFamily: 'var(--font-mono)', marginBottom: model.description ? '6px' : '0' }}>
                    {model.uploaded_at}
                  </div>
                  {model.description && (
                    <div style={{ fontSize: '13px', color: 'var(--text2)' }}>{model.description}</div>
                  )}
                </div>

                {!model.is_active && (
                  <button className="set-active-btn" onClick={() => handleSetActive(model.id)}>
                    Set Active
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default ModelUploadPage;
