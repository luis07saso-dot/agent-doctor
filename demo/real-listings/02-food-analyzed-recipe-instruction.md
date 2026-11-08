# Food Analyzed Recipe Instruction — TrueForge Agent Doctor demo

Doctor (live scorer) findings: chat_protocol, readme_sections, readme, rating, description, handle, avatar, starter_prompts
Agent findings: chat_protocol, readme_sections, readme, description, rating, handle, avatar, starter_prompts

## New description

Analyzes recipes for home cooks: ingredient breakdown, nutrition estimates, and instruction review.

## New keywords

recipe analysis, nutrition estimates, ingredient breakdown, cooking instructions, home cooks, food analysis

## New starter prompts

- Can you analyze my banana bread recipe and estimate its calories and macros?
- Are my cooking instructions clear enough for a beginner to follow?
- What substitutions can make this recipe healthier?
- How can I improve the step-by-step instructions in my recipe?

## New README

# Food Analyzed Recipe Instruction

## Summary

Food Analyzed Recipe Instruction is a recipe analysis agent for home cooks and anyone who wants to understand and improve what they cook. Send it a recipe — its title, ingredients, and cooking instructions — and it returns food analysis: an ingredient breakdown, nutrition estimates for calories and macros, and a review of the step-by-step instructions for clarity and completeness. It then suggests improvements and substitutions you can apply right away.

## Key features

- **Ingredient breakdown**: every ingredient in your recipe explained, with the role it plays in the dish.
- **Nutrition estimates**: approximate calories, protein, carbs, and fat per serving, drawn from standard food tables.
- **Instruction analysis**: your cooking instructions reviewed step by step for clarity, completeness, missing times and temperatures, and sensible ordering.
- **Improvements and substitutions**: fixes for weak or ambiguous steps, swaps for dietary needs, and ideas to make the dish healthier.
- **Plain-language feedback**: analysis written for everyday home cooks, not just professionals.

## Usage

Paste a recipe in a single message and ask what you want to know. Include the title, the full ingredient list, and the numbered cooking instructions so the analysis has everything it needs.

    User: Banana bread — 3 ripe bananas, 2 cups flour, 1/2 cup sugar, 2 eggs, 1/2 cup melted butter. Mash the bananas, stir everything together, bake at 350°F for 60 minutes. Analyze this recipe.
    Agent: Here is your analysis. Ingredient breakdown: bananas add moisture and sweetness, flour builds structure, butter and eggs add richness and binding. Nutrition estimates: about 250 calories, 4 g protein, 38 g carbs, and 10 g fat per slice across 12 slices. Instruction analysis: your cooking instructions are mostly clear, but I would add "cream the butter and sugar first" and "test with a toothpick at 55 minutes." Substitution idea: replace half the sugar with mashed dates for a less sweet loaf.

You can follow up with questions such as asking for healthier substitutions or clearer wording for a single step.

## Use cases

Home cooks use it before trying a new dish to see what they are about to eat and to fix confusing steps in advance. It helps when adapting a recipe to a dietary need, when a dish keeps coming out wrong and you suspect the instructions, and when writing down a family recipe so others can follow it. Food bloggers and cooking class teachers can use it to check instructions before publishing them.

## Limitations

Nutrition figures are approximations based on standard food tables, not medical advice, and they vary with brands and exact amounts. The agent works on text recipes only: it does not read images or attachments, does not recognize food from photos, and does not order groceries or arrange delivery. Very long recipes may need to be sent in parts, and uncommon regional ingredients are estimated with less precision.

## Metadata

- **Version**: 1.0.0
- **Category**: Food & Cooking
- **Data source**: Nutrition estimates are derived from standard public food composition tables; no external or live services are used.

