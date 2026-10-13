import pandas as pd
from datasets import Dataset
from transformers import AutoTokenizer, AutoModelForSequenceClassification, TrainingArguments, Trainer
import torch

print("\n[SYS] Loading Dataset...")
# 1. Load the CSV data
df = pd.read_csv("dataset.csv")

# Convert pandas dataframe to HuggingFace Dataset
hg_dataset = Dataset.from_pandas(df)

# Split into 80% training and 20% validation
split_dataset = hg_dataset.train_test_split(test_size=0.2, seed=42)
train_dataset = split_dataset['train']
eval_dataset = split_dataset['test']

print("[SYS] Initializing Tokenizer and Model...")
# 2. Load the base Tagalog tokenizer and model
model_name = "jcblaise/roberta-tagalog-base"
tokenizer = AutoTokenizer.from_pretrained(model_name)

# Notice we use 'AutoModelForSequenceClassification' now, telling it we have 4 categories
model = AutoModelForSequenceClassification.from_pretrained(
    model_name, 
    num_labels=4,
    ignore_mismatched_sizes=True
)

# 3. Tokenize the dataset
def tokenize_function(examples):
    return tokenizer(examples["text"], padding="max_length", truncation=True, max_length=128)

tokenized_train = train_dataset.map(tokenize_function, batched=True)
tokenized_eval = eval_dataset.map(tokenize_function, batched=True)

# 4. Set up the Training Arguments
training_args = TrainingArguments(
    output_dir="./securelink_tagalogbert",
    eval_strategy="epoch",
    learning_rate=2e-5,
    per_device_train_batch_size=8,
    per_device_eval_batch_size=8,
    num_train_epochs=5,
    weight_decay=0.01,
    logging_dir='./logs',
    logging_steps=10,
    save_strategy="epoch",
    load_best_model_at_end=True,
)

# 5. Initialize the Trainer
trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=tokenized_train,
    eval_dataset=tokenized_eval,
)

print("\n[SYS] Beginning Model Training...")
# 6. Train the model!
trainer.train()

print("\n[SYS] Saving Fine-Tuned Model...")
# 7. Save the newly trained model locally
model.save_pretrained("./securelink_final_model")
tokenizer.save_pretrained("./securelink_final_model")
print("[SYS] Training complete! Your custom model is saved in ./securelink_final_model")