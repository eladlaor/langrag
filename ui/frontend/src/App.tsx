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
import "bootstrap/dist/css/bootstrap.min.css";
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
        <header className="bg-primary text-white py-4 mb-4">
          <Container className="d-flex justify-content-between align-items-center">
            <div>
              <h1 className="mb-0">LangTalks Newsletter Generator</h1>
              <p className="mb-0 mt-2">Generate automated newsletters from WhatsApp group chats</p>
            </div>
            <div className="d-flex align-items-center gap-3">
              {currentUser && (
                <small className="text-white-50" data-testid="current-user">
                  {currentUser.email} ({currentUser.role})
                </small>
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

        <Container>
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

        <footer className="bg-light py-3 mt-5">
          <Container>
            <p className="text-center text-muted mb-0">
              <small>
                Powered by FastAPI + LangGraph |{" "}
                <a
                  href={`${API_BASE_URL || ""}/docs`}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  API Documentation
                </a>
              </small>
            </p>
          </Container>
        </footer>
      </div>
    </ErrorBoundary>
  );
}

export default App;
