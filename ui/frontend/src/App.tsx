/**
 * Main App Component
 */

import React, { useState } from "react";
import { Container, Tab, Tabs } from "react-bootstrap";
import { API_BASE_URL } from "./constants";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { PeriodicNewsletterForm } from "./components/PeriodicNewsletterForm";
import { ResultsDisplay } from "./components/ResultsDisplay";
import { RunsBrowser } from "./components/RunsBrowser";
import { SchedulesPage } from "./components/SchedulesPage";
import { PeriodicNewsletterResponse } from "./types";
import "bootstrap/dist/css/bootstrap.min.css";
import "./App.css";

function App() {
  const [periodicResults, setPeriodicResults] = useState<PeriodicNewsletterResponse | null>(null);
  const [activeTab, setActiveTab] = useState<string>("periodic");

  const handlePeriodicSuccess = (results: PeriodicNewsletterResponse) => {
    setPeriodicResults(results);
  };

  return (
    <ErrorBoundary>
      <div className="App">
        <header className="bg-primary text-white py-4 mb-4">
          <Container>
            <h1 className="mb-0">LangTalks Newsletter Generator</h1>
            <p className="mb-0 mt-2">Generate automated newsletters from WhatsApp group chats</p>
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
