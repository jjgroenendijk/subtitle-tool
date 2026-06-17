// Live job progress over Server-Sent Events. One script drives both the
// dashboard (any job) and the job detail page (one specific job). It only runs
// when the page opts in via the body's data-page attribute.

(function () {
  "use strict";

  // Confirm-before-submit applies on every page (e.g. clear history).
  setupConfirmForms();

  const page = document.body.dataset.page;
  if (page === "config") {
    setupConfig();
    return;
  }
  if (page === "library") {
    setupLibrary();
    return;
  }
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
    const stop = document.getElementById("live-stop");

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
      if (stop) {
        stop.hidden = false;
      }
    });

    source.addEventListener("file_processed", function (event) {
      const data = JSON.parse(event.data);
      panel.hidden = false;
      progress.max = data.total || 1;
      progress.value = data.processed;
      counts.textContent = data.processed + " of " + data.total + " files processed";
      file.textContent = describeFile(data.file);
      link.href = "/jobs/" + data.job_id;
      if (stop) {
        stop.hidden = false;
      }
    });

    source.addEventListener("job_finished", function (event) {
      const data = JSON.parse(event.data);
      status.textContent = data.status;
      status.className = "status status-" + data.status;
      if (stop) {
        stop.hidden = true;
      }
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
    const stop = document.getElementById("job-stop");

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
      if (stop) {
        stop.hidden = true;
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

  // --- Confirm-before-submit -------------------------------------------------

  function setupConfirmForms() {
    document.querySelectorAll("form[data-confirm]").forEach(function (form) {
      form.addEventListener("submit", function (event) {
        if (!window.confirm(form.dataset.confirm)) {
          event.preventDefault();
        }
      });
    });
  }

  // --- Library page: filter to videos missing wanted languages --------------

  function setupLibrary() {
    const toggle = document.getElementById("gaps-only");
    const table = document.getElementById("library");
    if (!toggle || !table) {
      return;
    }
    toggle.addEventListener("change", function () {
      table.classList.toggle("gaps-only", toggle.checked);
    });
  }

  // --- Configuration page: server-side directory picker ---------------------

  function setupConfig() {
    document.querySelectorAll(".dir-picker").forEach(initDirPicker);
    document.querySelectorAll(".lang-picker").forEach(initLangPicker);
  }

  function initLangPicker(picker) {
    const filter = picker.querySelector(".lang-filter");
    const options = Array.prototype.slice.call(picker.querySelectorAll(".lang-option"));
    const count = picker.querySelector(".lang-count");

    function updateCount() {
      const selected = options.filter(function (option) {
        return option.querySelector("input").checked;
      }).length;
      if (count) {
        count.textContent = selected + " selected";
      }
    }

    if (filter) {
      filter.addEventListener("input", function () {
        const term = filter.value.trim().toLowerCase();
        options.forEach(function (option) {
          const match = option.textContent.toLowerCase().indexOf(term) !== -1;
          option.hidden = term !== "" && !match;
        });
      });
    }

    picker.addEventListener("change", updateCount);
    updateCount();
  }

  function initDirPicker(picker) {
    const textarea = document.getElementById(picker.dataset.target);
    if (!textarea) {
      return;
    }
    const selected = parseLines(textarea.value);

    const list = document.createElement("ul");
    list.className = "path-list";
    picker.appendChild(list);

    const addBtn = document.createElement("button");
    addBtn.type = "button";
    addBtn.className = "secondary";
    addBtn.textContent = "Add directory";
    picker.appendChild(addBtn);

    const browser = document.createElement("div");
    browser.className = "dir-browser";
    browser.hidden = true;
    picker.appendChild(browser);

    function sync() {
      textarea.value = selected.join("\n");
      renderList();
    }

    function renderList() {
      list.textContent = "";
      if (!selected.length) {
        const li = document.createElement("li");
        li.className = "muted";
        li.textContent = "No directories selected yet.";
        list.appendChild(li);
        return;
      }
      selected.forEach(function (path, index) {
        const li = document.createElement("li");
        const code = document.createElement("code");
        code.textContent = path;
        li.appendChild(code);
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "link-button";
        remove.textContent = "remove";
        remove.addEventListener("click", function () {
          selected.splice(index, 1);
          sync();
        });
        li.appendChild(remove);
        list.appendChild(li);
      });
    }

    addBtn.addEventListener("click", function () {
      browser.hidden = !browser.hidden;
      if (!browser.hidden) {
        loadDir(null);
      }
    });

    function loadDir(path) {
      const url = path ? "/api/browse?path=" + encodeURIComponent(path) : "/api/browse";
      browser.textContent = "Loading…";
      fetch(url)
        .then(function (response) {
          return response.json().then(function (data) {
            return { ok: response.ok, data: data };
          });
        })
        .then(function (result) {
          if (!result.ok) {
            showBrowserError(result.data.error || "Could not list that directory.");
            return;
          }
          renderBrowser(result.data);
        })
        .catch(function () {
          showBrowserError("Could not reach the server.");
        });
    }

    function showBrowserError(message) {
      browser.textContent = "";
      const error = document.createElement("p");
      error.className = "error-text";
      error.textContent = "[ERROR] " + message;
      browser.appendChild(error);
    }

    function renderBrowser(data) {
      browser.textContent = "";

      const current = document.createElement("div");
      current.className = "dir-current";
      const code = document.createElement("code");
      code.textContent = data.path;
      current.appendChild(code);
      const addHere = document.createElement("button");
      addHere.type = "button";
      addHere.textContent = "Add this directory";
      addHere.addEventListener("click", function () {
        if (selected.indexOf(data.path) === -1) {
          selected.push(data.path);
          sync();
        }
        browser.hidden = true;
      });
      current.appendChild(addHere);
      browser.appendChild(current);

      const entries = document.createElement("ul");
      entries.className = "dir-entries";
      if (data.parent !== null) {
        entries.appendChild(dirItem("↑ parent directory", data.parent));
      }
      data.entries.forEach(function (entry) {
        entries.appendChild(dirItem(entry.name, entry.path));
      });
      if (!data.entries.length) {
        const li = document.createElement("li");
        li.className = "muted";
        li.textContent = "No subdirectories here.";
        entries.appendChild(li);
      }
      browser.appendChild(entries);
    }

    function dirItem(label, path) {
      const li = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "link-button";
      button.textContent = label;
      button.addEventListener("click", function () {
        loadDir(path);
      });
      li.appendChild(button);
      return li;
    }

    renderList();
  }

  function parseLines(text) {
    return text
      .split("\n")
      .map(function (line) {
        return line.trim();
      })
      .filter(Boolean);
  }
})();
