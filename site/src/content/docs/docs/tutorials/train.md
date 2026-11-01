---
title: Train your own picture style
description: Teach a picture model your own subject (a person, a pet, a product) or style from a few pictures, then use it in Pictures.
---

**Train** teaches a picture model something new from your own pictures:

- **A subject:** a person, a pet or a thing. Afterwards, ask for it anywhere: *your dog on the moon*, *your mug on a
  beach*, *you as a watercolour painting*.
- **A style:** a look shared by your pictures, such as your illustrations, a kind of painting or a photo style. Afterwards,
  draw anything that way.

It trains on this computer, and your pictures never leave it. (To teach a chat model your writing voice, see
[Train a chat model](/docs/tutorials/train-chat/).) The result is a small add-on for the picture model (a
*LoRA*), which you then choose on the [Pictures](/docs/tutorials/pictures/) page.

## What you need

- **An NVIDIA graphics card:** 6 GB or more for Stable Diffusion 1.5, 12 GB for SDXL. Training on a Mac or on the
  processor isn't supported yet.
- **A Stable Diffusion 1.5 or SDXL picture model**, from **Get models → Pictures**. Stable Diffusion 1.5 (about 2.6 GB)
  trains in minutes; SDXL makes bigger, more detailed pictures and takes longer. Other picture models (FLUX, for
  example) can't be trained yet.
- **The AI libraries for pictures.** If they're missing, the Train page offers to install them. If you installed them
  before wanna.sh 0.7, it asks to add one more library (PEFT); that's a small download.

## 1. Choose what to teach

Open **Train** in the sidebar. Under **What do you want to teach it?**, choose **A subject** or **A style**.

## 2. Add pictures

Drop 3 to 50 pictures onto the page, or press **Choose pictures**. 10 to 20 works best. Good pictures make the
difference:

| For a subject | For a style |
| --- | --- |
| Only that subject, clearly visible: one person, one pet, one thing. | Different subjects, all in the same style. |
| Vary everything else: backgrounds, angles, lighting, clothes. | Vary the subjects as much as you can. |
| Whatever stays the same in every picture gets learned too: if every photo has an orange wall behind your dog, the orange wall comes with it. | Whatever they have in common is what it learns. |

Pictures are cropped to a square around the middle, so keep the subject centred. PNG, JPEG and WebP all work.

## 3. Name it

- **Name:** for you, such as *Rex* or *My sketches*.
- **Trigger word:** a made-up word you'll put in descriptions to call it up. wanna.sh suggests one from the name (*Rex*
  becomes *rexzx*). Use a word that isn't a real one, so the model learns it fresh instead of mixing it up with
  something it knows.
- **What is it?** (subjects only): one or two words, such as *dog*, *woman* or *mug*. It helps the model place your
  subject among things it already knows.

The page shows how to ask for it afterwards, for example *a photo of rexzx dog on a beach*.

## 4. Choose the picture model and train

Choose the picture model to train. A trained style only works with the model it was trained on. The page estimates how
long it will take on your graphics card; as a guide, on an RTX 3060:

| Model | 10 pictures | Graphics memory |
| --- | --- | --- |
| Stable Diffusion 1.5 | about 7 minutes | about 3.5 GB |
| SDXL | about 25 minutes | about 10 GB |

Press **Start training**. Training uses one graphics card; if it's short of free memory, wanna.sh stops its own
models on that card first. You can keep
using the rest of wanna.sh meanwhile, and leave the page: progress shows when you come back. **Stop** ends a run early.

When it's done, you see three sample pictures made with it. Closing wanna.sh stops training, and the run shows *Stopped
when wanna.sh closed*; press **Train again** to start it over with the same pictures.

## 5. Use it

Press **Use it in Pictures**. The Pictures page opens with the right model and your style chosen, and a description to
start from. Put your trigger word in your descriptions:

- *a photo of rexzx dog wearing a party hat*
- *rexzx dog as a pencil sketch*
- *a city street at night, in the style of myskzx*

Later, choose it under **Style** in the prompt bar (it appears when the chosen model has trained styles). Under
**More settings**, **How strongly to use** it sets its strength:

- **Too strong** (everything starts to look like your pictures, even things you didn't ask for, or it copies their
  backgrounds): lower it, to around 70%.
- **Too weak** (it doesn't look like your subject): raise it, or train again with more, more varied pictures, or more
  steps.

## Advanced settings

Under **Show advanced settings**, **Training steps** sets how long it trains. The default grows with the number of
pictures (80 steps per picture for a subject, from 400 to 1,500; 100 per picture for a style, from 600 to 2,000). More
steps learn more closely, but too many make it copy your pictures exactly and ignore your descriptions.

Behind the scenes it trains a rank-16 LoRA on the picture model's attention layers, at 512 pixels for Stable Diffusion
1.5 and 1024 for SDXL, with every picture captioned *a photo of &lt;trigger word&gt; &lt;what it is&gt;* (or *a picture
in the style of &lt;trigger word&gt;*).

## Where it's kept

Each trained style is a folder in `~/.wanna/training`: your pictures, the trained LoRA
(`lora/pytorch_lora_weights.safetensors`, in the format diffusers and most Stable Diffusion tools read), and the
samples. **Delete** on the Train page removes the folder.

From apps, use a trained style with the [pictures API](/docs/api/images/#trained-styles).
