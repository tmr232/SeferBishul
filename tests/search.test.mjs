import { test } from "node:test";
import assert from "node:assert/strict";
import { searchRecipes } from "../src/sefer_bishul/static/search-engine.mjs";

const recipes = [
  { title: "לֶחֶם", ingredients: "קמח שמן", instructions: "ללוש היטב", text: "לֶחֶם קמח שמן ללוש היטב" },
  { title: "שמן", ingredients: "זיתים", instructions: "לסנן קמח", text: "שמן זיתים לסנן קמח" },
  { title: "גוצ׳וג׳אנג", ingredients: "מלח", instructions: "לערבב", text: "גוצ׳וג׳אנג מלח לערבב" },
];

test("field selection limits every search word to the selected field", () => {
  assert.deepEqual(searchRecipes(recipes, "קמח", "ingredients"), [recipes[0]]);
  assert.deepEqual(searchRecipes(recipes, "קמח", "instructions"), [recipes[1]]);
  assert.deepEqual(searchRecipes(recipes, "שמן", "title"), [recipes[1]]);
  assert.deepEqual(searchRecipes(recipes, "קמח ללוש", "text"), [recipes[0]]);
  assert.deepEqual(searchRecipes(recipes, "קמח ללוש", "ingredients"), []);
});

test("Hebrew marks, apostrophes, punctuation and empty queries", () => {
  assert.deepEqual(searchRecipes(recipes, "לחם", "title"), [recipes[0]]);
  assert.deepEqual(searchRecipes(recipes, "גוצ'וג'אנג", "title"), [recipes[2]]);
  assert.deepEqual(searchRecipes(recipes, "  קמח, שמן! ", "ingredients"), [recipes[0]]);
  assert.deepEqual(searchRecipes(recipes, "   ", "text"), recipes);
  assert.deepEqual(searchRecipes(recipes, "אין כזה", "text"), []);
});
