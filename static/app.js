"use strict";

// ---- Index page: file list, sample loader, double-submit guard ----
const form = document.getElementById("screenForm");
if (form) {
  const input = document.getElementById("resumes");
  const list = document.getElementById("fileList");

  input.addEventListener("change", () => {
    renderFiles([...input.files]);
  });

  const renderFiles = (files) => {
    list.replaceChildren();
    files.forEach((f) => {
      const li = document.createElement("li");
      li.textContent = `${f.name} (${Math.max(1, Math.round(f.size / 1024))} KB)`;
      list.append(li);
    });
  };

  const dropZone = document.querySelector(".upload-box");
  ["dragenter", "dragover"].forEach((eventName) => {
    dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropZone.classList.add("is-dragging");
    });
  });
  ["dragleave", "drop"].forEach((eventName) => {
    dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropZone.classList.remove("is-dragging");
    });
  });
  dropZone.addEventListener("drop", (event) => {
    const files = [...event.dataTransfer.files];
    if (files.length) {
      input.files = event.dataTransfer.files;
      renderFiles(files);
    }
  });

  document.getElementById("loadSample").addEventListener("click", async (e) => {
    try {
      const res = await fetch(e.currentTarget.dataset.url);
      if (!res.ok) throw new Error();
      document.getElementById("jd_text").value = await res.text();
    } catch {
      alert("Could not load the sample job description.");
    }
  });

  form.addEventListener("submit", () => {
    const btn = document.getElementById("submitBtn");
    btn.disabled = true;
    btn.textContent = "Analysing resumes…";
  });
}

// ---- Results page: CSV export ----
const csvBtn = document.getElementById("csvBtn");
if (csvBtn) {
  csvBtn.addEventListener("click", () => {
    const data = JSON.parse(document.getElementById("resultsData").textContent);
    const cols = [
      ["Rank", (r) => r.rank], ["Name", (r) => r.name], ["Email", (r) => r.email || ""],
      ["Phone", (r) => r.phone || ""], ["Score", (r) => r.score], ["Verdict", (r) => r.label],
      ["Experience (yrs)", (r) => r.experience_years], ["Education", (r) => r.education_label],
      ["Matched required", (r) => r.matched_required.join("; ")],
      ["Missing required", (r) => r.missing_required.join("; ")],
      ["Certifications", (r) => r.certifications.join("; ")],
      ["Flags", (r) => r.flags.join("; ")], ["File", (r) => r.filename],
    ];
    // Neutralise spreadsheet formula injection (=, +, -, @ at the start of a cell).
    const cell = (v) => {
      let s = String(v ?? "");
      if (/^[=+\-@\t\r]/.test(s)) s = "'" + s;
      return `"${s.replace(/"/g, '""')}"`;
    };
    const lines = [cols.map((c) => cell(c[0])).join(",")];
    data.forEach((r) => lines.push(cols.map((c) => cell(c[1](r))).join(",")));
    const blob = new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "ranked-candidates.csv";
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  });
}
