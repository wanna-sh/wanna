---
title: Your own AI for a task
description: Teach wanna.sh a task of your own from examples (sort, flag, score, pull details out, answer your way), see how well it does, and use it everywhere.
---

**Tasks** teaches the AI a job of your own from examples of what goes in and the answer you want. Some things
people use it for:

- **Flag things:** is this card transaction fraud? Is this review fake? Is this part damaged (from a photo)?
- **Sort things:** which team should this support email go to? Which category is this product in?
- **Score things:** what will this house sell for? How many days will this order take?
- **Pull details out, or answer your way:** turn an email into `{"name": ..., "date": ..., "amount": ...}`, or
  reply in your shop's voice.

You don't need to know how to train AI. wanna.sh picks the method from your examples, tests the result on examples
it didn't learn from, and tells you in plain words how well it does. Everything stays on this computer.

## 1. Make a task

Open **Tasks** in the sidebar. Give it a name, and under **What should it do?** describe it in a sentence (for
example *Say whether a card transaction is fraud (yes) or not (no)*). Then add your examples:

- **A table:** CSV, TSV, JSON or JSONL, one row per example. One column holds the answer; the others are what goes
  in. Up to 200,000 rows.
- **Pictures:** press **Choose a folder of pictures**, and choose a folder with one folder inside per answer
  (`damaged/`, `fine/`). The folder names are the answers.
- **No answers yet?** A table with only what goes in, or pictures without folders. A chat model can draft the
  answers for you (step 3).

Press **Create**.

## 2. Check what it read

The task's page shows what wanna.sh made of your examples: how many there are, what kind of task it is (*from a
table to a label*, for example), and the answers it found, with how many of each.

For a table, it guesses which column is the answer (a column called *answer*, *label*, *class*, *target* and so on,
or else the last one). Change it under **The answer is in**, and choose the columns that go in under **What goes
in**. A column of numbers, a column of categories (a few values repeated) and a column of free text are read
differently; the kind shows next to each.

What it learns depends on the answer:

| What goes in | The answer | How it learns | Needs |
| --- | --- | --- | --- |
| A table of numbers and categories | A label, or a number | Gradient-boosted trees: usually seconds | Nothing extra |
| Text (one column) | A label | Your search model reads each example, then it learns from what it read | A search model, from **Knowledge** |
| Pictures | A label | Your search model looks at each picture, then it learns from what it saw | A search model that can see pictures, such as Qwen3 VL Embedding |
| Text | Writing (or details as JSON) | A chat model is trained on your examples | The AI libraries and an NVIDIA graphics card, as for [training a chat model](/docs/tutorials/train-chat/) |

## 3. Give or check the answers

The table of examples shows each one with its answer, which you can change. For a task with labels, list the answers
it can give under **Answers it can give** (as plain words: a chat model drafts better with *cars* than
*rec.autos*).

If some examples have no answer, **Draft the missing answers** has a chat model answer up to 200 at a time. Drafts
are marked **AI draft**; check them under **AI drafts to check**, correct any that are wrong, and press the tick (or
**These 25 look right**). **Think before each answer** lets models that can reason do so first: slower, and more
often right. As a guide, Qwen3 8B sorting 40 newsgroup posts into 4 topics drafted 38 right when thinking first, in
about 5 minutes, and 29 right without; with the topics named in plain words, it got 36 right without thinking.
Pictures need a chat model that can see them: Gemma 4 E4B drafted 17 of 18 cat, dog and car pictures right in 24
seconds, and the 18th, meant to be a car, showed only a sofa.

## 4. Train and test it

Press **Train**. When it's done, **How it did** says what to expect on new examples, because every result comes
from examples it didn't learn from: with fewer than 2,000 examples, each is tested once by a version trained on the
other four fifths; with more, it's tested on a fifth held back. For writing, a tenth of the examples (3 to 50) is
held back.

- **Labels:** how often it's right, next to how often always giving the most common answer would be right. With
  lopsided examples (2 frauds in 100) that second number is high, so look at what it finds of each answer: *yes:
  found 13 of 28; when it said yes, it was right 13 of 44 times*.
- **Yes or no:** a table shows, for each threshold, how many of the rarer answer it catches and how many it flags
  wrongly. wanna.sh picks a balance; press **Use this** on another row to suit you: catching more fraud costs more
  false alarms.
- **Numbers:** how far off it is on average, and next to it how far off always guessing the average would be.
- **Writing:** what it wrote next to what you expected. For answers that are JSON, how many fields it got right.
- **What it looks at most** (tables): which columns matter most to its answers.
- **Examples it got wrong**, the ones it was surest about first. These often show answers that were wrong in the
  examples.

As a guide, on this computer: 569 breast tumour measurements (a standard test set) were sorted right 96.7% of the
time, against 62.7% for always saying the most common answer, in 3 seconds; 600 newsgroup posts were sorted into 4
topics right 94.3% of the time, in 24 seconds.

To improve it, add more examples, especially of what it gets wrong, and train again.

## 5. Use it

Under **Use it**:

- **Try it:** fill in an input and press **Answer it**. Labels come with how sure it is.
- **Answer a whole file:** choose a table with the same columns; you get it back as a CSV with an `answer` column
  added (and `confidence` for labels).
- **In Chat and Code:** while **Let the AI use it** is on, the task is a tool the AI can use (its name is shown, such
  as `task_card_fraud_f443`) whenever **Tools** is on in [Chat](/docs/tutorials/chat/), and in
  [Code](/docs/tutorials/code/). Ask *is this transaction fraud?* with the details, and it asks your task. Picture
  tasks can't be tools yet.
- **From apps:** with [the tasks API](/docs/api/native/#tasks).

## Where it's kept

Each task is a folder in `~/.wanna/tasks`: `task.json` (what it is), `examples.jsonl` (your examples and answers),
any pictures, `model.joblib` (what it learned, for labels and numbers) and `report.json` (how it did). A task that
writes is a [trained chat model](/docs/tutorials/train-chat/) too, listed on the Train page and in **My models**.
