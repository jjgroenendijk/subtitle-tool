// Live job progress over Server-Sent Events. One script drives both the
// dashboard (any job) and the job detail page (one specific job). It only runs
// when the page opts in via the body's data-page attribute.

(function () {
  "use strict";

  const page = document.body.dataset.page;
  if (page !== "dashboard" && page !== "job") {
    return;
  }

  const source = new EventSource("/events");

  if (page === "dashboard") {
    setupDashboard(source);
  } else {
    setupJobDetail(source);
  }

  function setupDashboard(source) {
    const panel = document.getElementById("live");
    const status = document.getElementById("live-status");
    const progress = document.getElementById("live-progress");
    const counts = document.getElementById("live-counts");
    const file = document.getElementById("live-file");
    const link = document.getElementById("live-link");

    source.addEventListener("job_started", function (event) {
      const data = JSON.parse(event.data);
      panel.hidden = false;
      status.textContent = "running";
      status.className = "status status-running";
      progress.value = 0;
      progress.max = 1;
      counts.textContent = "";
      file.textContent = "";
      link.href = "/jobs/" + data.job_id;
    });

    source.addEventListener("file_processed", function (event) {
      const data = JSON.parse(event.data);
      panel.hidden = false;
      progress.max = data.total || 1;
      progress.value = data.processed;
      counts.textContent = data.processed + " of " + data.total + " files processed";
      file.textContent = describeFile(data.file);
      link.href = "/jobs/" + data.job_id;
    });

    source.addEventListener("job_finished", function (event) {
      const data = JSON.parse(event.data);
      status.textContent = data.status;
      status.className = "status status-" + data.status;
      counts.textContent =
        data.changed + " changed, " + data.warnings + " warnings, " + data.errors + " errors";
      // Refresh the recent-jobs table now the run is recorded.
      setTimeout(function () {
        window.location.reload();
      }, 800);
    });
  }

  function setupJobDetail(source) {
    const jobId = parseInt(document.body.dataset.jobId, 10);
    const progress = document.getElementById("live-progress");
    const rows = document.getElementById("file-rows");
    const status = document.getElementById("job-status");

    source.addEventListener("file_processed", function (event) {
      const data = JSON.parse(event.data);
      if (data.job_id !== jobId) {
        return;
      }
      if (progress) {
        progress.max = data.total || 1;
        progress.value = data.processed;
      }
      appendRow(rows, data.file);
    });

    source.addEventListener("job_finished", function (event) {
      const data = JSON.parse(event.data);
      if (data.job_id !== jobId) {
        return;
      }
      if (status) {
        status.textContent = data.status;
        status.className = "status status-" + data.status;
      }
      setText("job-changed", data.changed);
      setText("job-warnings", data.warnings);
      setText("job-errors", data.errors);
      source.close();
    });
  }

  function appendRow(tbody, file) {
    if (!file || !(file.changed || file.warnings.length || file.error)) {
      return;
    }
    const placeholder = document.getElementById("no-files");
    if (placeholder) {
      placeholder.remove();
    }
    const tr = document.createElement("tr");

    const nameCell = document.createElement("td");
    const src = document.createElement("code");
    src.textContent = file.source;
    nameCell.appendChild(src);
    if (file.target !== file.source) {
      nameCell.appendChild(document.createElement("br"));
      const arrow = document.createElement("span");
      arrow.textContent = "→ ";
      const tgt = document.createElement("code");
      tgt.textContent = file.target;
      nameCell.appendChild(arrow);
      nameCell.appendChild(tgt);
    }

    const actionCell = document.createElement("td");
    file.actions.forEach(function (action) {
      const div = document.createElement("div");
      const tag = document.createElement("span");
      tag.className = "tag";
      tag.textContent = action[0];
      div.appendChild(tag);
      div.appendChild(document.createTextNode(" " + action[1]));
      actionCell.appendChild(div);
    });

    const noteCell = document.createElement("td");
    file.warnings.forEach(function (warning) {
      const div = document.createElement("div");
      div.className = "muted";
      div.textContent = "[WARNING] " + warning;
      noteCell.appendChild(div);
    });
    if (file.error) {
      const div = document.createElement("div");
      div.className = "error-text";
      div.textContent = "[ERROR] " + file.error;
      noteCell.appendChild(div);
    }

    tr.appendChild(nameCell);
    tr.appendChild(actionCell);
    tr.appendChild(noteCell);
    tbody.appendChild(tr);
  }

  function describeFile(file) {
    if (!file) {
      return "";
    }
    if (file.error) {
      return "[ERROR] " + file.source;
    }
    if (file.changed) {
      return "changed: " + file.source;
    }
    if (file.warnings.length) {
      return "[WARNING] " + file.source;
    }
    return file.source;
  }

  function setText(id, value) {
    const node = document.getElementById(id);
    if (node) {
      node.textContent = value;
    }
  }
})();
