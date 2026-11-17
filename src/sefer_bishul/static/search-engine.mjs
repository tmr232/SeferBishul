export function normalize(text) {
  return text
    .normalize("NFKD")
    .replace(/[\u0591-\u05BD\u05BF-\u05C7]/g, "")
    .toLocaleLowerCase("he")
    .replace(/[׳״'"’]/g, "")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim();
}

export function searchRecipes(recipes, query, field) {
  const words = normalize(query).split(/\s+/).filter(Boolean);
  return recipes.filter((recipe) => {
    const text = normalize(recipe[field]);
    return words.every((word) => text.includes(word));
  });
}
