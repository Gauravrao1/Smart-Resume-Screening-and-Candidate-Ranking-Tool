"use strict";

// ---- Index page: file list, sample loader, drag-drop, submit guard ----
const form = document.getElementById("screenForm");
if (form) {
  const input = document.getElementById("resumes");
  const list = document.getElementById("fileList");
  const uploadBox = document.getElementById("uploadBox");

  const renderFiles = (files) => {
    list.replaceChildren();
    files.forEach((f, i) => {
      const li = document.createElement("li");
      li.textContent = `${f.name} (${Math.max(1, Math.round(f.size / 1024))} KB)`;
      li.style.animationDelay = `${i * 0.05}s`;
      list.append(li);
    });
    // Mark upload box as having files
    if (files.length) {
      uploadBox.classList.add("has-files");
    } else {
      uploadBox.classList.remove("has-files");
    }
  };

  input.addEventListener("change", () => {
    renderFiles([...input.files]);
  });

  // Drag and drop
  ["dragenter", "dragover"].forEach((eventName) => {
    uploadBox.addEventListener(eventName, (event) => {
      event.preventDefault();
      uploadBox.classList.add("is-dragging");
    });
  });
  ["dragleave", "drop"].forEach((eventName) => {
    uploadBox.addEventListener(eventName, (event) => {
      event.preventDefault();
      uploadBox.classList.remove("is-dragging");
    });
  });
  uploadBox.addEventListener("drop", (event) => {
    const files = [...event.dataTransfer.files];
    if (files.length) {
      input.files = event.dataTransfer.files;
      renderFiles(files);
    }
  });

  // Load sample JD
  document.getElementById("loadSample").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    const originalText = btn.textContent;
    btn.textContent = "Loading…";
    btn.disabled = true;
    try {
      const res = await fetch(btn.dataset.url);
      if (!res.ok) throw new Error();
      document.getElementById("jd_text").value = await res.text();
      btn.textContent = "✓ Loaded!";
      setTimeout(() => { btn.textContent = originalText; btn.disabled = false; }, 1500);
    } catch {
      btn.textContent = originalText;
      btn.disabled = false;
      alert("Could not load the sample job description.");
    }
  });

  // Submit guard — prevent double-submit and show loading state
  form.addEventListener("submit", () => {
    const btn = document.getElementById("submitBtn");
    btn.disabled = true;
    btn.classList.add("is-loading");
    btn.innerHTML = "Analysing resumes…";
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
    const blob = new Blob(["\uFEFF" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "ranked-candidates.csv";
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);

    // Button feedback
    const originalText = csvBtn.textContent;
    csvBtn.textContent = "✓ Downloaded!";
    setTimeout(() => { csvBtn.textContent = originalText; }, 2000);
  });
}

// ---- Smooth scroll for anchor links ----
document.querySelectorAll('a[href^="#"]').forEach((anchor) => {
  anchor.addEventListener("click", (e) => {
    const target = document.querySelector(anchor.getAttribute("href"));
    if (target) {
      e.preventDefault();
      target.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  });
});
