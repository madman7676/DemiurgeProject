import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles.css";

// Frontend bootstrap only; gameplay state wiring comes later.
ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

