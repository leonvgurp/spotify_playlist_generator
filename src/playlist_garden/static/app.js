"use strict";
const $ = (id) => document.getElementById(id);
const csrf = document.querySelector('meta[name="csrf-token"]').content;
let bands = [],
  current = null,
  busy = false;
const node = (tag, text, cls) => {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (cls) el.className = cls;
  return el;
};
function error(message) {
  $("error").textContent = message;
  $("error").hidden = !message;
}
async function api(path, body, method) {
  const response = await fetch(path, {
    method: method || (body === undefined ? "GET" : "POST"),
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail),
    );
  return data;
}
function run(fn) {
  return async (...args) => {
    error("");
    try {
      await fn(...args);
    } catch (e) {
      error(e.message);
    }
  };
}
function requestSpec() {
  if (!$("settings-form").reportValidity())
    throw new Error("Check your playlist settings.");
  if (!bands.length) throw new Error("Add at least one band.");
  return {
    bands,
    title: $("title").value.trim(),
    count: Number($("count").value),
    seed: Number($("seed").value),
    include_inputs: $("include").checked,
    discovery_mode: $("discovery").value,
    discovery_percent: Number($("percent").value),
    ordering: $("ordering").value,
  };
}
function controls() {
  $("mix-controls").hidden = $("discovery").value === "relevance";
  $("percent-label").textContent = $("percent").value + "%";
  $("include-help").textContent = $("include").checked
    ? "Your selected songs get a guaranteed place."
    : "Input songs guide discovery, with no guaranteed places.";
  $("mix-help").textContent = $("include").checked
    ? "Applies to songs added after your mandatory inputs."
    : "Applies to the entire generated playlist.";
}
for (const id of ["discovery", "percent", "include"])
  $(id).addEventListener("input", controls);
async function updateStatus() {
  const s = await api("/api/status");
  $("connect").textContent = s.connected
    ? "Disconnect Spotify"
    : "Connect Spotify";
  $("connect").onclick = run(async () => {
    if (s.connected) {
      await api("/api/disconnect", {});
      await updateStatus();
    } else {
      const r = await api("/api/connect", {});
      location.assign(r.url);
    }
  });
  const missing = [];
  if (!s.spotify_configured) missing.push("SPOTIFY_CLIENT_ID");
  if (!s.lastfm_configured) missing.push("LASTFM_API_KEY");
  $("setup").hidden = !missing.length;
  $("setup").textContent = missing.length
    ? `One-time setup: add ${missing.join(" and ")} to the .env file, then restart the app. See README.md for the exact steps. Your playlists will stay local until you save to Spotify.`
    : "";
}
function autocomplete(input, results, kind, band, onSelect) {
  let timer,
    sequence = 0;
  input.addEventListener("input", () => {
    clearTimeout(timer);
    const turn = ++sequence;
    results.replaceChildren();
    const q = input.value.trim();
    if (q.length < 2) return;
    timer = setTimeout(async () => {
      results.textContent = "Searching…";
      try {
        const params = new URLSearchParams({ q, kind });
        if (band) {
          params.set("artist_id", band.artist.id);
          params.set("artist_name", band.artist.name);
        }
        const matches = await api("/api/search?" + params);
        if (turn !== sequence) return;
        results.replaceChildren();
        if (!matches.length)
          results.textContent =
            "No matches. Try another spelling or a Spotify link.";
        for (const item of matches) {
          const button = node("button", item.name, "result");
          button.type = "button";
          if (kind === "track")
            button.append(
              node(
                "small",
                `${item.artists.map((a) => a.name).join(", ")} · ${item.album}`,
              ),
            );
          else button.append(node("small", `Spotify artist · ${item.id}`));
          button.onclick = run(async () => {
            onSelect(item);
            input.value = "";
            results.replaceChildren();
            ++sequence;
          });
          results.append(button);
        }
      } catch (e) {
        if (turn === sequence) results.textContent = e.message;
      }
    }, 350);
  });
}
autocomplete(
  $("artist-search"),
  $("artist-results"),
  "artist",
  null,
  (artist) => {
    if (bands.length >= 10) throw new Error("You can add up to 10 bands.");
    if (bands.some((b) => b.artist.id === artist.id))
      throw new Error("This band is already included.");
    bands.push({ artist, tracks: [] });
    renderBands();
  },
);
function renderBands() {
  $("bands").replaceChildren();
  $("seed-empty").hidden = bands.length > 0;
  $("band-count").textContent = `${bands.length} / 10 bands`;
  bands.forEach((band, i) => {
    const block = node("div", undefined, "band"),
      head = node("div", undefined, "band-header");
    head.append(
      node("span", String(i + 1).padStart(2, "0"), "band-index"),
      node("h3", band.artist.name),
    );
    const remove = node("button", "Remove", "quiet");
    remove.onclick = () => {
      bands.splice(i, 1);
      renderBands();
    };
    head.append(remove);
    block.append(head);
    for (const track of band.tracks) {
      const line = node("div", undefined, "seed-song");
      line.append(node("span", `♫  ${track.name}`));
      const del = node("button", "×", "quiet");
      del.setAttribute("aria-label", `Remove ${track.name}`);
      del.onclick = () => {
        band.tracks = band.tracks.filter((t) => t.id !== track.id);
        renderBands();
      };
      line.append(del);
      block.append(line);
    }
    if (band.tracks.length < 10) {
      const id = `song-${i}`,
        label = node("label", `Add a song · ${band.tracks.length}/10`);
      label.htmlFor = id;
      const input = node("input");
      input.id = id;
      input.type = "search";
      input.placeholder = "Song name or Spotify track link";
      input.autocomplete = "off";
      const results = node("div", undefined, "results");
      results.setAttribute("aria-live", "polite");
      autocomplete(input, results, "track", band, (track) => {
        if (band.tracks.some((t) => t.id === track.id))
          throw new Error("This song is already included.");
        band.tracks.push(track);
        renderBands();
      });
      block.append(label, input, results);
    }
    $("bands").append(block);
  });
}
function fillSettings(spec) {
  bands = structuredClone(spec.bands);
  renderBands();
  for (const key of ["title", "count", "seed", "ordering"])
    $(key).value = spec[key];
  $("include").checked = spec.include_inputs;
  $("discovery").value = spec.discovery_mode;
  $("percent").value = spec.discovery_percent;
  controls();
}
async function loadGeneration(id) {
  const doc = await api(`/api/generations/${id}`);
  fillSettings(doc.request);
  renderPreview(doc);
}
function renderPreview(doc) {
  current = doc;
  $("preview").hidden = false;
  $("count").value = doc.request.count;
  $("preview-title").textContent = doc.request.title || "Untitled playlist";
  $("preview-meta").textContent =
    `Seed ${doc.request.seed} · Saved data from ${new Date(doc.snapshot.captured_at).toLocaleString()}${doc.edited ? " · Manually edited" : ""}`;
  $("preview-count").textContent = `${doc.tracks.length} songs`;
  $("warnings").textContent = doc.snapshot.warnings.join(" ");
  $("shortage").hidden = !doc.shortage;
  $("shortage").textContent = doc.shortage?.message || "";
  $("save").disabled = doc.status !== "ready";
  $("csv").href = `/api/generations/${doc.id}/download/csv`;
  $("json").href = `/api/generations/${doc.id}/download/json`;
  $("tracks").replaceChildren();
  const frozen = doc.export.status && doc.export.status !== "not_created";
  doc.tracks.forEach((row, i) => {
    const tr = node("tr"),
      title = node("td"),
      song = node("a", row.track.name, "track-name");
    song.href = `https://open.spotify.com/track/${row.track.id}`;
    song.target = "_blank";
    song.rel = "noreferrer";
    title.append(song);
    if (row.input)
      title.append(
        node("span", row.locked ? "INPUT · LOCKED" : "INPUT", "input-badge"),
      );
    title.append(
      node(
        "div",
        row.track.artists.map((a) => a.name).join(", "),
        "track-artist",
      ),
    );
    const actions = node("td", undefined, "actions");
    if (!row.locked && !frozen)
      for (const action of ["replace", "remove"]) {
        const button = node(
          "button",
          action === "replace" ? "Replace" : "Remove",
          "quiet",
        );
        button.onclick = run(async () => {
          button.disabled = true;
          try {
            renderPreview(
              await api(`/api/generations/${current.id}/edit`, {
                track_id: row.track.id,
                action,
              }),
            );
            await history();
          } finally {
            button.disabled = false;
          }
        });
        actions.append(button);
      }
    tr.append(
      node("td", String(i + 1)),
      title,
      node("td", row.explanation, "explanation"),
      actions,
    );
    $("tracks").append(tr);
  });
  $("export-result").replaceChildren();
  if (doc.export.status === "complete") {
    const a = node("a", "Saved. Open your playlist in Spotify ↗");
    a.href = doc.export.url;
    a.target = "_blank";
    a.rel = "noreferrer";
    $("export-result").append(a);
  }
  $("recovery").hidden =
    !["creating", "uncertain"].includes(doc.export.status) ||
    !!doc.export.playlist_id;
}
async function history() {
  const docs = await api("/api/generations");
  $("history").replaceChildren();
  if (!docs.length)
    $("history").append(
      node("p", "Your saved generations will appear here.", "muted"),
    );
  for (const d of docs) {
    const row = node("div", undefined, "history-row"),
      button = node("button", d.request.title || "Untitled playlist");
    button.onclick = run(async () => {
      await loadGeneration(d.id);
      $("preview").scrollIntoView({ behavior: "smooth" });
    });
    row.append(
      button,
      node(
        "small",
        `${d.request.count} songs · seed ${d.request.seed} · ${new Date(d.created_at).toLocaleString()}`,
      ),
    );
    $("history").append(row);
  }
}
async function generate() {
  if (busy) return;
  const spec = requestSpec();
  busy = true;
  $("generate").disabled = true;
  $("refresh").disabled = true;
  $("progress").hidden = false;
  try {
    const { job_id } = await api("/api/generations", spec);
    while (true) {
      const job = await api(`/api/jobs/${job_id}`);
      $("progress-text").textContent = job.message;
      if (job.status === "failed") throw new Error(job.message);
      if (job.status === "complete") {
        await loadGeneration(job.generation_id);
        await history();
        $("preview").scrollIntoView({ behavior: "smooth" });
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, 900));
    }
  } finally {
    busy = false;
    $("generate").disabled = false;
    $("refresh").disabled = false;
    $("progress").hidden = true;
  }
}
$("settings-form").addEventListener(
  "submit",
  run(async (event) => {
    event.preventDefault();
    await generate();
  }),
);
$("refresh").onclick = run(generate);
$("reproduce").onclick = run(async () => {
  const doc = await api(`/api/generations/${current.id}/reproduce`, null);
  fillSettings(doc.request);
  renderPreview(doc);
  await history();
});
$("apply").onclick = run(async () => {
  renderPreview(
    await api(`/api/generations/${current.id}/reproduce`, requestSpec()),
  );
  await history();
});
$("save").onclick = run(async () => {
  $("save").disabled = true;
  try {
    await api(`/api/generations/${current.id}/export`, {});
  } finally {
    renderPreview(await api(`/api/generations/${current.id}`));
  }
});
$("recover").onclick = run(async () => {
  await api(`/api/generations/${current.id}/recover`, {
    reference: $("recovery-link").value,
  });
  renderPreview(await api(`/api/generations/${current.id}`));
});
$("reset-export").onclick = run(async () => {
  if (
    !confirm(
      "Have you checked Spotify and confirmed that this generation did not create a playlist? Resetting can create a duplicate if one already exists.",
    )
  )
    return;
  await api(`/api/generations/${current.id}/reset-export`, {
    confirm_no_playlist: true,
  });
  renderPreview(await api(`/api/generations/${current.id}`));
});
run(async () => {
  controls();
  await updateStatus();
  await history();
})();
