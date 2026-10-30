## What I Built

I built a Prompt Lab that uses the Anthropic API to test prompting techniques with Claude Sonnet 5. I used the lab to complete four separate Wildframe Coffee Roasters tasks using zero-shot, one-shot, few-shot, and chain-of-thought prompting. Each task was run in a separate conversation and exported to Markdown so the prompts, responses, and any refinements were preserved.

## Why This Approach

Task 1 - Technique: zero-shot

The subscriber perks task was an open-ended creative task that did not require Claude to reproduce an existing format or style example. The company context, requested number of ideas, and output constraints gave Claude enough direction without examples that might unnecessarily narrow its creativity.

Task 2 - Technique: one-shot

The bean card task required Claude to follow an established house format with the same labels in the same order. The single Huila bean card demonstrated both the required structure and how the "Real talk:" field should reflect Wildframe's slightly irreverent personality without requiring a lengthy description of the desired result.

Task 3 - Technique: few-shot

The customer reply task depended heavily on reproducing Wildframe's voice across different types of customer interactions. The four previous customer replies demonstrated how Wildframe responds to questions, complaints, praise, and straightforward requests, giving Claude several examples from which to infer the brand's common voice.

Task 4 - Technique: chain-of-thought

The pop-up location task required comparing quantitative information, evaluating a fixed rent budget, and weighing several factors before making a decision. Asking Claude to work through expected purchases, rent, revenue versus rent, and the overall tradeoffs step by step made its reasoning visible so I could evaluate both the calculations and the assumptions supporting its recommendation.

## Example Run

Model: claude-sonnet-5

### System

Wildframe Coffee Roasters is a fictional specialty coffee roaster that sells beans online and through a monthly subscription. Brand voice: warm, plainspoken, and a little irreverent, with no corporate jargon. Customers: environmentally conscious urban professionals.

### You

You are a marketing analyst for Wildframe, who can run one four-week pop-up stand this spring, with a total rent budget of $5,000 for the four weeks. Pop-up location data (weekly figures from comparable past events):

Riverside Farmers Market: 9,000 visitors per week; 2% of visitors buy; average sale $14 (mostly whole-bean bags); rent $900 per week.
Union Station concourse: 30,000 visitors per week; 0.5% of visitors buy; average sale $6 (mostly single cups); rent $2,000 per week.
Campus library atrium: 6,000 visitors per week; 3% of visitors buy; average sale $5 (single cups); rent $600 per week.

Use the location data to decide where it should go. 
Work through this step by step before recommending:
1. Estimate expected purchases from each location.
2. Judge how well the rent for each location fits the budget.
3. Judge the purchases vs rent for each location
4. Weigh those factors against each other.

Required format: the response must end with a single line that starts with Recommendation: followed by the location's name.

### Claude

# Pop-Up Location Analysis: Spring 2024

## Step 1: Expected Purchases & Revenue (Weekly)

| Location | Visitors | Conversion | Purchases/wk | Avg Sale | Revenue/wk |
|---|---|---|---|---|---|
| Riverside Farmers Market | 9,000 | 2% | 180 | $14 | $2,520 |
| Union Station | 30,000 | 0.5% | 150 | $6 | $900 |
| Campus Library Atrium | 6,000 | 3% | 180 | $5 | $900 |

Riverside and Campus Library tie on raw purchase count, but Riverside's bigger ticket size (whole-bean bags vs. single cups) makes its revenue nearly 3x higher.

## Step 2: Rent vs. Budget (4 Weeks, $5,000 cap)

| Location | Weekly Rent | 4-Week Total | Fits Budget? |
|---|---|---|---|
| Riverside | $900 | $3,600 | Yes, with $1,400 to spare |
| Union Station | $2,000 | $8,000 | No — blows past budget by $3,000 |
| Campus Library | $600 | $2,400 | Yes, with $2,600 to spare |

Union Station is already on thin ice here. We simply can't run it for four weeks without going over budget, full stop.

## Step 3: Purchases & Revenue vs. Rent

| Location | Weekly Profit (Revenue − Rent) | 4-Week Profit |
|---|---|---|
| Riverside | $2,520 − $900 = **$1,620** | **$6,480** |
| Union Station | $900 − $2,000 = **−$1,100** | **−$4,400** |
| Campus Library | $900 − $600 = **$300** | **$1,200** |

Union Station loses money every single week — high foot traffic doesn't mean much if people are just passing through for their train, not their coffee fix.

## Step 4: Weighing It All Together

- **Union Station** is out. It costs too much, converts too few people, and actually loses money. Lots of eyeballs, not enough wallets.
- **Campus Library** is cheap and efficient per dollar of rent, but the profit ceiling is low — $1,200 over four weeks barely covers staff time, let alone makes the pop-up worth the hassle.
- **Riverside Farmers Market** hits the sweet spot: solid foot traffic, the highest-value customers (people buying bags, not just a to-go cup), and a healthy profit margin that leaves room in the budget for extras like samples or a nicer tent setup.

Riverside isn't just the best option on paper — it's the one that matches how Wildframe actually makes money: real coffee fans buying real beans, not just caffeine-starved commuters grabbing the fastest cup in sight.

Recommendation: Riverside Farmers Market

### You

Revise the analysis without changing the recommendation. Do not call revenue minus rent “profit”; label it “revenue after rent, before other expenses.” Remove the unsupported year and avoid assumptions about staffing costs or visitor behavior that are not contained in the supplied data. Keep the required final Recommendation line.

### Claude

# Pop-Up Location Analysis: Spring Pop-Up Decision

## Step 1: Expected Purchases & Revenue (Weekly)

| Location | Visitors | Conversion | Purchases/wk | Avg Sale | Revenue/wk |
|---|---|---|---|---|---|
| Riverside Farmers Market | 9,000 | 2% | 180 | $14 | $2,520 |
| Union Station | 30,000 | 0.5% | 150 | $6 | $900 |
| Campus Library Atrium | 6,000 | 3% | 180 | $5 | $900 |

Riverside and Campus Library tie on raw purchase count, but Riverside's higher average sale makes its revenue nearly 3x higher.

## Step 2: Rent vs. Budget (4 Weeks, $5,000 cap)

| Location | Weekly Rent | 4-Week Total | Fits Budget? |
|---|---|---|---|
| Riverside | $900 | $3,600 | Yes, with $1,400 to spare |
| Union Station | $2,000 | $8,000 | No — exceeds budget by $3,000 |
| Campus Library | $600 | $2,400 | Yes, with $2,600 to spare |

Union Station cannot run for four weeks without exceeding the budget, regardless of other factors.

## Step 3: Purchases & Revenue vs. Rent

| Location | Weekly Revenue After Rent, Before Other Expenses | 4-Week Total |
|---|---|---|
| Riverside | $2,520 − $900 = **$1,620** | **$6,480** |
| Union Station | $900 − $2,000 = **−$1,100** | **−$4,400** |
| Campus Library | $900 − $600 = **$300** | **$1,200** |

Union Station's figures show a negative weekly result before any other costs are factored in.

## Step 4: Weighing It All Together

- **Union Station** doesn't fit the budget and shows a negative revenue-after-rent figure even before other expenses are considered. It's out on both counts.
- **Campus Library** fits comfortably within budget and is efficient relative to its rent, but its total revenue after rent ($1,200 over four weeks) is modest compared to the other viable option.
- **Riverside Farmers Market** fits the budget with room to spare, and produces the highest revenue after rent, before other expenses, of the three locations ($6,480 over four weeks).

Based on the supplied data alone — visitor counts, conversion rates, average sale, and rent — Riverside Farmers Market produces the strongest numbers across every step of the analysis.

Recommendation: Riverside Farmers Market

## Reflection

The four tasks showed me that choosing the appropriate prompting technique can make the prompt simpler while still producing a strong result. The zero-shot task produced six surprisingly creative subscriber perks without needing examples, while the one-shot bean card task showed how much information one well-chosen example can communicate. I especially liked the new "Real talk:" lines Claude generated because the single Huila example communicated both the required structure and the personality of that field.

I found the chain-of-thought task particularly useful because seeing Claude's reasoning made problems easier to identify. Its first analysis reached the same recommendation I expected, but it called revenue minus rent "profit" and introduced assumptions that were not supported by the supplied data. A focused refinement corrected those problems without requiring a different prompting approach.

I am least certain about the system context I carried into Task 4. Chain-of-thought was the right technique because making the reasoning visible allowed me to identify and correct unsupported assumptions without changing the recommendation. However, I wonder whether the full Wildframe brand voice, particularly the instruction to be a little irreverent, encouraged some unnecessary improvisation in what was primarily an analytical task. If I repeated the experiment, I would keep the same chain-of-thought approach but use a more focused system prompt that retained the necessary company context while emphasizing evidence-based analysis. This reinforced for me that context is important, but more context is not automatically better context. The context needs to support the specific task.
