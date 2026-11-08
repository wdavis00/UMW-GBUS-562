## What I Built

I extended the Week 3 RAG tool so it can answer questions from different document collections using the --docs option while maintaining a separate Chroma database for each collection. I also added a --save option that records the retrieved chunks, similarity scores, source files, and Claude's final answer for later review. I used the tool with Larkfield Credit Union's documents to create seven saved runs: Question 1 before and after correcting the document collection, followed by Questions 2 through 6.

## Why This Approach

Chunking method: structure

Makes sense on its own: Yes, each chunk follows the documents' existing headings and sections and includes enough surrounding information to understand that section independently.

Label and source: Both, each chunk begins with its document title and section heading and also records the source filename it came from.

Short enough: Yes, the largest Larkfield chunk is 129 words (179 tokens), under the roughly 190-word limit, so the embedding model reads every chunk in full.

## Example Run

#1  similarity 0.569  funds-availability-policy.html
Funds Availability Policy - Check deposits
Source file: funds-availability-policy.html
Version: Version 3 (current). Owner: Deposit Operations.

For checks deposited at a branch or a Larkfield ATM, the first $275 of the day's check deposits is available on the next business day. The rest of the day's check deposits is available on the second business day after the day of deposit.

#2  similarity 0.562  funds-availability-policy.html
Funds Availability Policy - Mobile check deposits
Source file: funds-availability-policy.html
Version: Version 3 (current). Owner: Deposit Operations.

Checks deposited with the Larkfield mobile app follow the same availability as checks deposited at a branch. A member can deposit up to $5,000 per business day through the mobile app. Members should keep the paper check for 30 days after a mobile deposit, then destroy it.

#3  similarity 0.445  card-dispute-procedure.html
Debit Card Dispute Procedure - How much the member may have to pay
Source file: card-dispute-procedure.html
Version: Version 4 (current). Owner: Card Services.

A member's share of the loss from unauthorized debit card transactions depends on how quickly they report it. If the member reports a lost or stolen card within two business days of learning about it, they pay no more than $50. If they report it later than that, they may pay up to $500. If unauthorized transactions appear on a statement and the member does not report them within 60 days after the statement was sent, they may have to pay for transactions after those 60 days in full.

#4  similarity 0.439  funds-availability-policy.html
Funds Availability Policy - Longer holds
Source file: funds-availability-policy.html
Version: Version 3 (current). Owner: Deposit Operations.

Larkfield may hold check deposits for up to seven business days when the day's check deposits total more than $6,000, when the account has been open fewer than 30 days, when the account has been overdrawn repeatedly in the last six months, or when there is reason to doubt the check will be paid. The member is told about a longer hold when the deposit is made, or by mail if the hold is placed later.

ANSWER
Of a $2,000 check deposited at a branch today, the first $275 is available on the next business day; the remaining $1,725 is available on the second business day after the deposit [funds-availability-policy.html].

This assumes none of the "longer hold" conditions apply (e.g., day's total check deposits over $6,000, account open fewer than 30 days, repeated overdrafts, or doubt about the check being paid), which could extend the hold to up to seven business days [funds-availability-policy.html].

## Reflection

What was wrong: consumer-fee-schedule-v7.html was an obsolete Version 7 fee schedule that still identified itself as current. The Question 1 retrieval placed it second behind Version 8, giving Claude conflicting $29 and $35 overdraft fees.

How I fixed it: Moved consumer-fee-schedule-v7.html out of the active Larkfield document collection into larkfield-docs-archive, then rebuilt the Larkfield Chroma database so the obsolete chunks were no longer available for retrieval.

Prevention: Archive process would keep superseded documents available for historical reference while removing them from the active collection used to answer questions about current policies.

Question 6: Declined because retrieval returned weakly related chunks about certificate rates and fees rather than mortgage information, and Claude correctly stated that the provided documents did not answer the question.
