import { searchRecipes } from "./search-engine.mjs";

const form = document.querySelector("#search-form");
const query = document.querySelector("#query");
const clear = document.querySelector("#clear");
const field = form.elements.namedItem("field");
const filter = document.querySelector("#search-filter");
const results = document.querySelector("#results");
const status = document.querySelector("#search-status");
const retry = document.querySelector("#retry");
let recipes;
let pointerSelection = false;

function readURL() {
  const params = new URLSearchParams(location.search);
  query.value = params.get("q") || "";
  field.value = ["title", "ingredients", "instructions"].includes(
    params.get("field"),
  )
    ? params.get("field")
    : "text";
}

function render() {
  clear.hidden = !query.value;
  const selected = form.querySelector('input[name="field"]:checked');
  filter
    .querySelector("summary")
    .setAttribute(
      "aria-label",
      `איפה לחפש? ${selected.parentElement.textContent}`,
    );
  if (!recipes) return;
  const matches = searchRecipes(recipes, query.value, field.value);
  results.replaceChildren(
    ...matches.map((recipe) => {
      const item = document.createElement("li");
      const link = document.createElement("a");
      link.href = recipe.url;
      link.textContent = recipe.title;
      const arrow = document.createElement("span");
      arrow.setAttribute("aria-hidden", "true");
      arrow.textContent = "←";
      link.append(arrow);
      item.append(link);
      return item;
    }),
  );
  status.textContent = matches.length
    ? `${matches.length} מתכונים${query.value.trim() ? " נמצאו" : ""}`
    : "לא נמצאו מתכונים.";
}

function update() {
  const params = new URLSearchParams();
  if (query.value) params.set("q", query.value);
  if (field.value !== "text") params.set("field", field.value);
  history.replaceState(
    null,
    "",
    `${location.pathname}${params.size ? `?${params}` : ""}`,
  );
  render();
}

async function load() {
  retry.hidden = true;
  status.textContent = "טוענים את המתכונים…";
  try {
    const response = await fetch("search-index.json");
    if (!response.ok) throw new Error(response.status);
    recipes = await response.json();
    render();
  } catch {
    status.textContent = "לא הצלחנו לטעון את החיפוש. בדקו את החיבור ונסו שוב.";
    retry.hidden = false;
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  update();
  query.blur();
});
query.addEventListener("input", update);
form.addEventListener("change", (event) => {
  if (event.target.name !== "field") return;
  update();
});
filter.addEventListener("click", (event) => {
  // Labels forward zero-detail clicks, just like keyboard radio navigation.
  if (event.detail > 0 && event.target.closest("label"))
    pointerSelection = true;
  if (event.target.name !== "field" || !pointerSelection) return;
  pointerSelection = false;
  filter.open = false;
  filter.querySelector("summary").focus();
});
document.addEventListener("click", (event) => {
  if (!filter.contains(event.target)) filter.open = false;
});
filter.addEventListener("keydown", (event) => {
  if (
    event.key === "Escape" ||
    (event.key === "Enter" && event.target.name === "field")
  ) {
    event.preventDefault();
    filter.open = false;
    filter.querySelector("summary").focus();
  }
});
clear.addEventListener("click", () => {
  query.value = "";
  update();
  query.focus();
});
window.addEventListener("popstate", () => {
  readURL();
  render();
});
retry.addEventListener("click", load);
readURL();
render();
load();
