/**
 * Main App Component
 */

import React, { useState } from "react";
import { Button, Container, Tab, Tabs } from "react-bootstrap";
import { API_BASE_URL } from "./constants";
import { useAuth } from "./contexts/AuthContext";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { PeriodicNewsletterForm } from "./components/PeriodicNewsletterForm";
import { ResultsDisplay } from "./components/ResultsDisplay";
import { RunsBrowser } from "./components/RunsBrowser";
import { SchedulesPage } from "./components/SchedulesPage";
import { RAGChatPage } from "./components/rag/RAGChatPage";
import { UsersAdmin } from "./components/admin/UsersAdmin";
import { ExtractedImagesGallery } from "./components/admin/ExtractedImagesGallery";
import { PeriodicNewsletterResponse } from "./types";
import "./App.css";

function App() {
  const [periodicResults, setPeriodicResults] = useState<PeriodicNewsletterResponse | null>(null);
  const [activeTab, setActiveTab] = useState<string>("periodic");
  const { logout, currentUser, isAdmin } = useAuth();

  const handlePeriodicSuccess = (results: PeriodicNewsletterResponse) => {
    setPeriodicResults(results);
  };

  return (
    <ErrorBoundary>
      <div className="App">
        <header className="app-header py-3 mb-4">
          <Container className="d-flex justify-content-between align-items-center">
            <div>
              <h1 className="brand-mark">
                Lang<span className="brand-accent">RAG</span>
              </h1>
              <p className="brand-sub">Newsletter intelligence from community conversations</p>
            </div>
            <div className="d-flex align-items-center gap-3">
              {currentUser && (
                <span className="app-userline" data-testid="current-user">
                  {currentUser.email} · {currentUser.role}
                </span>
              )}
              <Button
                variant="outline-light"
                size="sm"
                onClick={() => {
                  void logout();
                }}
              >
                Log out
              </Button>
            </div>
          </Container>
        </header>

        <Container className="lr-rise">
          <Tabs
            activeKey={activeTab}
            onSelect={(k) => setActiveTab(k || "periodic")}
            className="mb-4"
          >
            <Tab eventKey="periodic" title="Periodic Newsletter">
              <PeriodicNewsletterForm onSuccess={handlePeriodicSuccess} />
              {activeTab === "periodic" && (
                <ResultsDisplay results={periodicResults} type="periodic" />
              )}
            </Tab>

            <Tab eventKey="browse" title="Browse Past Runs">
              <RunsBrowser />
            </Tab>

            <Tab eventKey="schedules" title="Schedules">
              <SchedulesPage />
            </Tab>

            <Tab eventKey="knowledge-chat" title="Knowledge Chat">
              <RAGChatPage />
            </Tab>

            {isAdmin && (
              <Tab eventKey="extracted-images" title="Extracted Images">
                {activeTab === "extracted-images" && <ExtractedImagesGallery />}
              </Tab>
            )}

            {isAdmin && (
              <Tab eventKey="users" title="Users">
                <UsersAdmin />
              </Tab>
            )}
          </Tabs>
        </Container>

        <footer className="py-4 mt-5" style={{ borderTop: "1px solid var(--rule)" }}>
          <Container className="d-flex justify-content-between align-items-center flex-wrap gap-2">
            <span className="eyebrow">LangRAG</span>
            <small className="text-muted">
              FastAPI + LangGraph ·{" "}
              <a
                href={`${API_BASE_URL || ""}/docs`}
                target="_blank"
                rel="noopener noreferrer"
              >
                API Documentation
              </a>
            </small>
          </Container>
        </footer>
      </div>
    </ErrorBoundary>
  );
}

export default App;
