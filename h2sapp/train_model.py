import os
import joblib
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import r2_score
from sklearn.model_selection import train_test_split

csv_path = "h2s_training_data.csv"
if not os.path.exists(csv_path):
  print(
      f"❌ Error: '{csv_path}' not found. Please run 'extract_data.py' first."
  )
  exit()

# Load dataset
df = pd.read_csv(csv_path)
X = df[["Mean_R", "Mean_G", "Mean_B"]]
y = df["Dose_ppm_hr"]

# Split data for validation
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42
)

# Train Random Forest Regressor
print("Training Random Forest model...")
model = RandomForestRegressor(n_estimators=100, random_state=42)
model.fit(X_train, y_train)

# Evaluate
predictions = model.predict(X_test)
score = r2_score(y_test, predictions)
print(f"Model R² Accuracy Score: {score:.2f}")

# Save model
joblib.dump(model, "h2s_rf_model.pkl")
print("SUCCESS: Model saved as 'h2s_rf_model.pkl'!")