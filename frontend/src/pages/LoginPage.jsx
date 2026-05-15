import React, { useState } from "react";

const API_BASE = "http://localhost:5000";

const LoginPage = ({ onLoginSuccess, theme, toggleTheme }) => {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e?.preventDefault();
    setError("");

    if (!username.trim() || !password) {
      setError("Please enter username and password.");
      return;
    }

    setLoading(true);
    
    // Simulate network delay
    await new Promise(resolve => setTimeout(resolve, 800));
    
    if (username === "admin" && password === "admin") {
      onLoginSuccess?.({ token: "admin-auth-token" });
    } else {
      setError("Invalid username or password.");
    }
    
    setLoading(false);
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        position: 'relative',
        background: "var(--bg, #0d1117)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "40px 20px",
        fontFamily: "'Segoe UI', system-ui, sans-serif",
      }}
    >
      <div
        style={{
          width: "100%",
          maxWidth: "460px",
          background: "var(--bg2, #161b22)",
          border: "1px solid var(--border, #30363d)",
          borderRadius: "12px",
          padding: "48px 44px 40px",
        }}
      >
        {/* ── Logo ── */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "8px",
            marginBottom: "28px",
          }}
        >
          <div
            style={{
              width: "10px",
              height: "10px",
              borderRadius: "50%",
              background: "var(--blue, #58a6ff)",
              boxShadow: "0 0 0 3px rgba(88,166,255,0.15)",
            }}
          />
          <div
            style={{
              fontSize: "16px",
              fontWeight: 700,
              color: "var(--text, #e6edf3)",
              letterSpacing: "0.5px",
            }}
          >
            <span style={{ color: "var(--blue, #58a6ff)" }}>SDN</span>·SEC
          </div>
        </div>

        {/* ── Heading ── */}
        <div
          style={{
            fontSize: "18px",
            fontWeight: 600,
            color: "var(--text, #e6edf3)",
            marginBottom: "4px",
          }}
        >
          Sign in
        </div>
        <div
          style={{
            fontSize: "12px",
            color: "var(--muted, #7d8590)",
            marginBottom: "28px",
            lineHeight: "1.5",
          }}
        >
          SDN Security Monitoring &amp; Control System
        </div>

        <form
          onSubmit={handleSubmit}
          style={{ display: "flex", flexDirection: "column", gap: "14px" }}
        >
          {/* ── Error Box ── */}
          {error && (
            <div
              style={{
                background: "rgba(248,81,73,0.08)",
                border: "1px solid rgba(248,81,73,0.25)",
                borderLeft: "3px solid var(--red, #f85149)",
                borderRadius: "0 7px 7px 0",
                padding: "9px 12px",
                fontSize: "12px",
                color: "var(--red, #f85149)",
              }}
            >
              {error}
            </div>
          )}

          {/* ── Username ── */}
          <div>
            <label
              style={{
                fontSize: "11px",
                fontWeight: 600,
                letterSpacing: "0.8px",
                textTransform: "uppercase",
                color: "var(--muted, #7d8590)",
                display: "block",
                marginBottom: "6px",
              }}
            >
              Username
            </label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              onKeyDown={(e) =>
                e.key === "Enter" && document.getElementById("login-pw").focus()
              }
              placeholder="admin"
              autoComplete="username"
              style={{
                width: "100%",
                padding: "10px 12px",
                background: "var(--bg, #0d1117)",
                border: "1px solid var(--border, #30363d)",
                borderRadius: "7px",
                color: "var(--text, #e6edf3)",
                fontSize: "13px",
                outline: "none",
                fontFamily: "inherit",
                transition: "border-color 0.15s",
              }}
              onFocus={(e) =>
                (e.target.style.borderColor = "var(--blue, #58a6ff)")
              }
              onBlur={(e) =>
                (e.target.style.borderColor = "var(--border, #30363d)")
              }
            />
          </div>

          {/* ── Password ── */}
          <div>
            <label
              style={{
                fontSize: "11px",
                fontWeight: 600,
                letterSpacing: "0.8px",
                textTransform: "uppercase",
                color: "var(--muted, #7d8590)",
                display: "block",
                marginBottom: "6px",
              }}
            >
              Password
            </label>
            <div style={{ position: "relative" }}>
              <input
                id="login-pw"
                type={showPw ? "text" : "password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
                placeholder="••••••••"
                autoComplete="current-password"
                style={{
                  width: "100%",
                  padding: "10px 36px 10px 12px",
                  background: "var(--bg, #0d1117)",
                  border: "1px solid var(--border, #30363d)",
                  borderRadius: "7px",
                  color: "var(--text, #e6edf3)",
                  fontSize: "13px",
                  outline: "none",
                  fontFamily: "inherit",
                  transition: "border-color 0.15s",
                }}
                onFocus={(e) =>
                  (e.target.style.borderColor = "var(--blue, #58a6ff)")
                }
                onBlur={(e) =>
                  (e.target.style.borderColor = "var(--border, #30363d)")
                }
              />
              <button
                type="button"
                onClick={() => setShowPw((v) => !v)}
                style={{
                  position: "absolute",
                  right: "10px",
                  top: "50%",
                  transform: "translateY(-50%)",
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  padding: "2px",
                  color: "var(--muted, #484f58)",
                  display: "flex",
                  alignItems: "center",
                  transition: "color 0.15s",
                }}
              >
                {showPw ? (
                  <svg
                    width="15"
                    height="15"
                    viewBox="0 0 16 16"
                    fill="currentColor"
                  >
                    <path d="M13.359 11.238C15.06 9.72 16 8 16 8s-3-5.5-8-5.5a7.028 7.028 0 0 0-2.79.588l.77.771A5.944 5.944 0 0 1 8 3.5c2.12 0 3.879 1.168 5.168 2.457A13.134 13.134 0 0 1 14.828 8c-.058.087-.122.183-.195.288-.335.48-.83 1.12-1.465 1.755-.165.165-.337.328-.517.486l.708.709z" />
                    <path d="M11.297 9.176a3.5 3.5 0 0 0-4.474-4.474l.823.823a2.5 2.5 0 0 1 2.829 2.829l.822.822zm-2.943 1.299.822.822a3.5 3.5 0 0 1-4.474-4.474l.823.823a2.5 2.5 0 0 0 2.829 2.829z" />
                    <path d="M3.35 5.47c-.18.16-.353.322-.518.487A13.134 13.134 0 0 0 1.172 8l.195.288c.335.48.83 1.12 1.465 1.755C4.121 11.332 5.881 12.5 8 12.5c.716 0 1.39-.133 2.02-.36l.77.772A7.029 7.029 0 0 1 8 13.5C3 13.5 0 8 0 8s.939-1.721 2.641-3.238l.708.709zm10.296 8.884-12-12 .708-.708 12 12-.708.708z" />
                  </svg>
                ) : (
                  <svg
                    width="15"
                    height="15"
                    viewBox="0 0 16 16"
                    fill="currentColor"
                  >
                    <path d="M16 8s-3-5.5-8-5.5S0 8 0 8s3 5.5 8 5.5S16 8 16 8zM1.173 8a13.133 13.133 0 0 1 1.66-2.043C4.12 4.668 5.88 3.5 8 3.5c2.12 0 3.879 1.168 5.168 2.457A13.133 13.133 0 0 1 14.828 8c-.058.087-.122.183-.195.288-.335.48-.83 1.12-1.465 1.755C11.879 11.332 10.119 12.5 8 12.5c-2.12 0-3.879-1.168-5.168-2.457A13.144 13.144 0 0 1 1.172 8z" />
                    <path d="M8 5.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5zM4.5 8a3.5 3.5 0 1 1 7 0 3.5 3.5 0 0 1-7 0z" />
                  </svg>
                )}
              </button>
            </div>
          </div>

          {/* ── Divider ── */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "10px",
              margin: "4px 0",
            }}
          >
            <div
              style={{
                flex: 1,
                height: "1px",
                background: "var(--bg3, #21262d)",
              }}
            />
            <span
              style={{
                fontSize: "10px",
                color: "var(--muted, #484f58)",
                letterSpacing: "0.5px",
              }}
            >
              SDN·SEC v2.0
            </span>
            <div
              style={{
                flex: 1,
                height: "1px",
                background: "var(--bg3, #21262d)",
              }}
            />
          </div>

          {/* ── Submit Button ── */}
          <button
            type="submit"
            disabled={loading}
            style={{
              width: "100%",
              padding: "11px",
              background: "var(--blue, #58a6ff)",
              color: "#0d1117",
              border: "none",
              borderRadius: "7px",
              fontSize: "13px",
              fontWeight: 700,
              cursor: loading ? "not-allowed" : "pointer",
              opacity: loading ? 0.6 : 1,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: "7px",
              fontFamily: "inherit",
              transition: "opacity 0.15s, transform 0.1s",
            }}
          >
            {loading ? (
              <>
                <svg
                  width="13"
                  height="13"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  style={{ animation: "spin 1s linear infinite" }}
                >
                  <path d="M21 12a9 9 0 1 1-6.219-8.56" />
                </svg>
                Signing in…
              </>
            ) : (
              <>
                <svg
                  width="13"
                  height="13"
                  viewBox="0 0 16 16"
                  fill="currentColor"
                >
                  <path
                    fillRule="evenodd"
                    d="M10 12.5a.5.5 0 0 1-.5.5h-8a.5.5 0 0 1-.5-.5v-9a.5.5 0 0 1 .5-.5h8a.5.5 0 0 1 .5.5v2a.5.5 0 0 0 1 0v-2A1.5 1.5 0 0 0 9.5 2h-8A1.5 1.5 0 0 0 0 3.5v9A1.5 1.5 0 0 0 1.5 14h8a1.5 1.5 0 0 0 1.5-1.5v-2a.5.5 0 0 0-1 0v2z"
                  />
                  <path
                    fillRule="evenodd"
                    d="M15.854 8.354a.5.5 0 0 0 0-.708l-3-3a.5.5 0 0 0-.708.708L14.293 7.5H5.5a.5.5 0 0 0 0 1h8.793l-2.147 2.146a.5.5 0 0 0 .708.708l3-3z"
                  />
                </svg>
                Sign in
              </>
            )}
          </button>
        </form>

        {/* ── Footer Badges ── */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "6px",
            marginTop: "22px",
            paddingTop: "18px",
            borderTop: "1px solid var(--bg3, #21262d)",
          }}
        >
          {[
            {
              label: "Mininet",
              color: "var(--blue, #58a6ff)",
              bg: "rgba(88,166,255,0.12)",
              border: "rgba(88,166,255,0.2)",
            },
            {
              label: "Ryu",
              color: "var(--green, #3fb950)",
              bg: "rgba(63,185,80,0.12)",
              border: "rgba(63,185,80,0.2)",
            },
          ].map((b) => (
            <span
              key={b.label}
              style={{
                fontSize: "9px",
                fontWeight: 700,
                letterSpacing: "0.8px",
                padding: "2px 7px",
                borderRadius: "20px",
                textTransform: "uppercase",
                color: b.color,
                background: b.bg,
                border: `1px solid ${b.border}`,
              }}
            >
              {b.label}
            </span>
          ))}
          <span
            style={{
              fontSize: "10px",
              color: "var(--muted, #484f58)",
              marginLeft: "auto",
            }}
          >
            Secure local access only
          </span>
        </div>
      </div>

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      <button
        onClick={toggleTheme}
        style={{
          position: "absolute",
          top: "20px",
          right: "24px",
          background: "none",
          border: "1px solid var(--border, #30363d)",
          borderRadius: "7px",
          padding: "7px 10px",
          cursor: "pointer",
          color: "var(--muted, #7d8590)",
          display: "flex",
          alignItems: "center",
          gap: "6px",
          fontSize: "12px",
          transition: "border-color 0.15s",
        }}
      >
        {theme === "dark" ? (
          <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor">
            <path d="M8 11a3 3 0 1 1 0-6 3 3 0 0 1 0 6zm0 1a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM8 0a.5.5 0 0 1 .5.5v2a.5.5 0 0 1-1 0v-2A.5.5 0 0 1 8 0zm0 13a.5.5 0 0 1 .5.5v2a.5.5 0 0 1-1 0v-2A.5.5 0 0 1 8 13zm8-5a.5.5 0 0 1-.5.5h-2a.5.5 0 0 1 0-1h2a.5.5 0 0 1 .5.5zM3 8a.5.5 0 0 1-.5.5h-2a.5.5 0 0 1 0-1h2A.5.5 0 0 1 3 8zm10.657-5.657a.5.5 0 0 1 0 .707l-1.414 1.415a.5.5 0 1 1-.707-.708l1.414-1.414a.5.5 0 0 1 .707 0zm-9.193 9.193a.5.5 0 0 1 0 .707L3.05 13.657a.5.5 0 0 1-.707-.707l1.414-1.414a.5.5 0 0 1 .707 0zm9.193 2.121a.5.5 0 0 1-.707 0l-1.414-1.414a.5.5 0 0 1 .707-.707l1.414 1.414a.5.5 0 0 1 0 .707zM4.464 4.465a.5.5 0 0 1-.707 0L2.343 3.05a.5.5 0 1 1 .707-.707l1.414 1.414a.5.5 0 0 1 0 .708z" />
          </svg>
        ) : (
          <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor">
            <path d="M6 .278a.768.768 0 0 1 .08.858 7.208 7.208 0 0 0-.878 3.46c0 4.021 3.278 7.277 7.318 7.277.527 0 1.04-.055 1.533-.16a.787.787 0 0 1 .81.316.733.733 0 0 1-.031.893A8.349 8.349 0 0 1 8.344 16C3.734 16 0 12.286 0 7.71 0 4.266 2.114 1.312 5.124.06A.752.752 0 0 1 6 .278z" />
          </svg>
        )}
        {theme === "dark" ? "Light" : "Dark"}
      </button>
    </div>
  );
};

export default LoginPage;
