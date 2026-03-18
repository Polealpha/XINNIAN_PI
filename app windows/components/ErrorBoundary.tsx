import React from "react";

type Props = {
  children: React.ReactNode;
};

type State = {
  hasError: boolean;
  message: string;
};

export class ErrorBoundary extends React.Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = {
      hasError: false,
      message: "",
    };
  }

  static getDerivedStateFromError(error: Error): State {
    return {
      hasError: true,
      message: error?.message || "Unknown renderer error",
    };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error("Renderer crash:", error, errorInfo);
  }

  render() {
    if (!this.state.hasError) {
      return this.props.children;
    }

    return (
      <div
        style={{
          width: "100vw",
          height: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#070b14",
          color: "#E2E8F0",
          fontFamily: "Segoe UI, sans-serif",
          padding: "24px",
          boxSizing: "border-box",
        }}
      >
        <div
          style={{
            width: "100%",
            maxWidth: "720px",
            border: "1px solid rgba(148,163,184,0.3)",
            borderRadius: "16px",
            background: "rgba(15,23,42,0.8)",
            padding: "20px",
            boxSizing: "border-box",
          }}
        >
          <div style={{ fontWeight: 700, fontSize: "18px", marginBottom: "10px" }}>
            桌面端渲染异常
          </div>
          <div style={{ color: "#94A3B8", fontSize: "13px", lineHeight: 1.6 }}>
            应用已捕获错误，建议重启软件。如持续出现，请把下面错误信息发给开发排查。
          </div>
          <pre
            style={{
              marginTop: "12px",
              marginBottom: "16px",
              padding: "12px",
              borderRadius: "8px",
              background: "rgba(2,6,23,0.7)",
              color: "#F8FAFC",
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              fontSize: "12px",
            }}
          >
            {this.state.message || "Unknown error"}
          </pre>
          <button
            onClick={() => window.location.reload()}
            style={{
              border: "1px solid rgba(99,102,241,0.45)",
              borderRadius: "999px",
              padding: "8px 16px",
              background: "rgba(99,102,241,0.2)",
              color: "#E2E8F0",
              cursor: "pointer",
              fontWeight: 700,
            }}
          >
            重新加载
          </button>
        </div>
      </div>
    );
  }
}
