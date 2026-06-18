// Client-side behavior for the server-rendered UI.
//
// Two layers live here. Live job progress over Server-Sent Events stays vanilla:
// it streams onto the dashboard and job detail pages and only runs when a page
// opts in via the body's data-page attribute. Page-local interactivity (the
// config language and directory pickers, the library view preferences and "show
// gaps only" toggle) is declared in the templates with Alpine.js and implemented
// by the named Alpine.data components registered below. Jinja/FastAPI remain the
// source of truth; Alpine only manages transient in-page state.
//
// This script loads before Alpine (see base.html) so the alpine:init listener is
// registered before Alpine's deferred start() dispatches that event.

(function () {
  "use strict";

  registerAlpineComponents();

  // Library column registry and storage keys for the libraryView component's
  // localStorage-backed view preferences. "name" is always shown, so it is not
  // listed; the rest default to visible except size/modified/subs.
  const LIBRARY_COLUMNS = {
    langs: true,
    count: true,
    missing: true,
    size: false,
    modified: false,
    subs: false,
  };
  const COLUMNS_KEY = "library.columns";
  const PATHS_KEY = "library.showPaths";

  // Confirm-before-submit applies on every page (e.g. clear history).
  setupConfirmForms();

  // The library page's view preferences and quick filter are the libraryView
  // Alpine component (registered below); no vanilla wiring or SSE is needed here.
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

  // Build a DOM element without innerHTML so every dynamic string stays text,
  // never markup. attrs maps "class"/"hidden"/event handlers ("onclick") and
  // any other key to a real attribute; a "text" key sets textContent. Children
  // are nodes or strings (strings become text nodes); falsy children are
  // skipped so callers can inline conditionals.
  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (key) {
        const value = attrs[key];
        if (key === "class") {
          node.className = value;
        } else if (key === "text") {
          node.textContent = value;
        } else if (key === "hidden") {
          node.hidden = Boolean(value);
        } else if (key.indexOf("on") === 0 && typeof value === "function") {
          node.addEventListener(key.slice(2), value);
        } else {
          node.setAttribute(key, value);
        }
      });
    }
    children.forEach(function (child) {
      if (!child && child !== 0) {
        return;
      }
      node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    });
    return node;
  }

  function appendRow(tbody, file) {
    if (!file || !(file.changed || file.warnings.length || file.error)) {
      return;
    }
    const placeholder = document.getElementById("no-files");
    if (placeholder) {
      placeholder.remove();
    }

    const nameCell = el("td", null, el("code", { text: file.source }));
    if (file.target !== file.source) {
      nameCell.appendChild(el("br"));
      nameCell.appendChild(el("span", { text: "→ " }));
      nameCell.appendChild(el("code", { text: file.target }));
    }

    const actionCell = el("td");
    file.actions.forEach(function (action) {
      actionCell.appendChild(
        el("div", null, el("span", { class: "tag", text: action[0] }), " " + action[1]),
      );
    });

    const noteCell = el("td");
    file.warnings.forEach(function (warning) {
      noteCell.appendChild(el("div", { class: "muted", text: "[WARNING] " + warning }));
    });
    if (file.error) {
      noteCell.appendChild(el("div", { class: "error-text", text: "[ERROR] " + file.error }));
    }

    tbody.appendChild(el("tr", null, nameCell, actionCell, noteCell));
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

  // --- Library view preferences storage helpers ------------------------------
  //
  // Column visibility and the path toggle are client-side CSS classes persisted
  // per browser; the libraryView Alpine component reads and writes them through
  // these helpers. The "show gaps only" filter is a server-side query param
  // handled by the separate libraryGaps component.

  function readPrefs(key, fallback) {
    const prefs = {};
    let stored = {};
    try {
      stored = JSON.parse(window.localStorage.getItem(key)) || {};
    } catch (err) {
      stored = {};
    }
    Object.keys(fallback).forEach(function (id) {
      prefs[id] = typeof stored[id] === "boolean" ? stored[id] : fallback[id];
    });
    return prefs;
  }

  function writePrefs(key, prefs) {
    try {
      window.localStorage.setItem(key, JSON.stringify(prefs));
    } catch (err) {
      /* localStorage unavailable (private mode); ignore. */
    }
  }

  function readFlag(key) {
    try {
      return window.localStorage.getItem(key) === "1";
    } catch (err) {
      return false;
    }
  }

  function writeFlag(key, value) {
    try {
      window.localStorage.setItem(key, value ? "1" : "0");
    } catch (err) {
      /* localStorage unavailable; ignore. */
    }
  }

  // --- Alpine.js page-local components ---------------------------------------
  //
  // Registered on alpine:init (fired by Alpine's deferred start). The templates
  // reference these by name in x-data. To stay compatible with the Alpine CSP
  // build, template expressions use only property and method references; all
  // real logic lives in these components, never in inline expressions.

  function registerAlpineComponents() {
    document.addEventListener("alpine:init", function () {
      window.Alpine.data("langPicker", langPicker);
      window.Alpine.data("dirPicker", dirPicker);
      window.Alpine.data("libraryView", libraryView);
      window.Alpine.data("libraryGaps", libraryGaps);
    });
  }

  // Config language picker: filters the server-rendered checkbox list as the
  // user types and reports how many languages are selected.
  function langPicker() {
    return {
      term: "",
      selected: 0,
      options: [],
      boxes: [],
      init() {
        this.options = Array.prototype.slice.call(this.$el.querySelectorAll(".lang-option"));
        this.boxes = this.options.map(function (option) {
          return option.querySelector("input");
        });
        this.$watch("term", this.applyFilter.bind(this));
        this.updateCount();
      },
      get countLabel() {
        return this.selected + " selected";
      },
      applyFilter() {
        const term = this.term.trim().toLowerCase();
        this.options.forEach(function (option) {
          const match = option.textContent.toLowerCase().indexOf(term) !== -1;
          option.hidden = term !== "" && !match;
        });
      },
      updateCount() {
        this.selected = this.boxes.filter(function (box) {
          return box.checked;
        }).length;
      },
    };
  }

  // Config directory picker: browses container directories via /api/browse and
  // edits the newline-separated textarea that the form submits. The textarea
  // value (text) is the single source of truth; the selected list is derived
  // from it, so manual edits and picker actions stay in sync.
  function dirPicker() {
    return {
      text: "",
      browsing: false,
      loading: false,
      error: null,
      current: null,
      init() {
        // Alpine runs this root init() before binding the descendant textarea's
        // x-model, so the server-rendered value is still intact to seed from.
        const textarea = this.$el.querySelector("textarea");
        this.text = textarea ? textarea.value : "";
      },
      get selected() {
        return this.lines();
      },
      get hasNoSelection() {
        return this.lines().length === 0;
      },
      get hasResult() {
        return !this.loading && !this.error && this.current !== null;
      },
      get hasParent() {
        return this.current !== null && this.current.parent !== null;
      },
      get hasNoEntries() {
        return this.current !== null && this.current.entries.length === 0;
      },
      get errorLabel() {
        return "[ERROR] " + this.error;
      },
      lines() {
        return this.text
          .split("\n")
          .map(function (line) {
            return line.trim();
          })
          .filter(Boolean);
      },
      toggleBrowser() {
        this.browsing = !this.browsing;
        if (this.browsing && this.current === null) {
          this.load(null);
        }
      },
      browseParent() {
        this.load(this.current.parent);
      },
      browseEntry(path) {
        this.load(path);
      },
      addCurrent() {
        this.addPath(this.current.path);
        this.browsing = false;
      },
      addPath(path) {
        const lines = this.lines();
        if (lines.indexOf(path) === -1) {
          lines.push(path);
          this.text = lines.join("\n");
        }
      },
      remove(index) {
        const lines = this.lines();
        lines.splice(index, 1);
        this.text = lines.join("\n");
      },
      load(path) {
        this.loading = true;
        this.error = null;
        const url = path ? "/api/browse?path=" + encodeURIComponent(path) : "/api/browse";
        const self = this;
        fetch(url)
          .then(function (response) {
            return response.json().then(function (data) {
              return { ok: response.ok, data: data };
            });
          })
          .then(function (result) {
            self.loading = false;
            if (!result.ok) {
              self.current = null;
              self.error = result.data.error || "Could not list that directory.";
              return;
            }
            self.current = result.data;
          })
          .catch(function () {
            self.loading = false;
            self.current = null;
            self.error = "Could not reach the server.";
          });
      },
    };
  }

  // Library view preferences: owns the per-browser column visibility, the
  // filename-vs-full-path choice, and a quick filter over the rows on the
  // current page. Column/path prefs persist in localStorage and drive the
  // table's CSS classes via tableClass; the quick filter only hides rows the
  // server already rendered, so it never touches pagination or the missing
  // filter. reset() restores the defaults and clears the filter.
  function libraryView() {
    return {
      columns: {},
      showPaths: false,
      filter: "",
      rows: [],
      visibleCount: 0,
      init() {
        this.columns = readPrefs(COLUMNS_KEY, LIBRARY_COLUMNS);
        this.showPaths = readFlag(PATHS_KEY);
        this.syncControls();
        this.rows = Array.prototype.slice.call(
          this.$el.querySelectorAll("#library tbody tr[data-name]"),
        );
        this.visibleCount = this.rows.length;
        this.$watch("filter", this.applyFilter.bind(this));
      },
      // CSS classes the table carries: hide-<col> per hidden column plus
      // show-paths when full paths are opted in. Reactive on columns/showPaths.
      get tableClass() {
        const self = this;
        const classes = Object.keys(LIBRARY_COLUMNS)
          .filter(function (id) {
            return !self.columns[id];
          })
          .map(function (id) {
            return "hide-" + id;
          });
        if (this.showPaths) {
          classes.push("show-paths");
        }
        return classes.join(" ");
      },
      get hasNoMatches() {
        return this.filter.trim() !== "" && this.visibleCount === 0;
      },
      // Mirror the stored prefs onto the rendered checkboxes so they reflect the
      // active view after a reload or a reset.
      syncControls() {
        const self = this;
        Object.keys(LIBRARY_COLUMNS).forEach(function (id) {
          const box = self.$el.querySelector('.col-toggle[value="' + id + '"]');
          if (box) {
            box.checked = self.columns[id];
          }
        });
        const path = this.$el.querySelector(".path-toggle");
        if (path) {
          path.checked = this.showPaths;
        }
      },
      setColumn(event) {
        this.columns[event.target.value] = event.target.checked;
        writePrefs(COLUMNS_KEY, this.columns);
      },
      setPaths(event) {
        this.showPaths = event.target.checked;
        writeFlag(PATHS_KEY, this.showPaths);
      },
      applyFilter() {
        const term = this.filter.trim().toLowerCase();
        let visible = 0;
        this.rows.forEach(function (row) {
          const match = term === "" || row.dataset.name.indexOf(term) !== -1;
          row.classList.toggle("filter-hidden", !match);
          if (match) {
            visible += 1;
          }
        });
        this.visibleCount = visible;
      },
      reset() {
        this.columns = Object.assign({}, LIBRARY_COLUMNS);
        this.showPaths = false;
        this.filter = "";
        writePrefs(COLUMNS_KEY, this.columns);
        writeFlag(PATHS_KEY, this.showPaths);
        this.syncControls();
        this.applyFilter();
      },
    };
  }

  // Library "show gaps only" toggle: a server-side filter, so flipping the box
  // navigates with the missing query param set or cleared and resets to page 1.
  function libraryGaps() {
    return {
      toggle(event) {
        const params = new URLSearchParams(window.location.search);
        if (event.target.checked) {
          params.set("missing", "1");
        } else {
          params.delete("missing");
        }
        params.delete("page");
        const query = params.toString();
        window.location.href = "/library" + (query ? "?" + query : "");
      },
    };
  }
})();
