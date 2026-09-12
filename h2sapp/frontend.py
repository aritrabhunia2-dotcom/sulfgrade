import cv2
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
import streamlit as st

st.set_page_config(
    page_title="AI H2S Strip Reader (Random Forest)",
    page_icon="🧪",
    layout="centered",
)

st.title("🧪 Advanced H2S Test Strip Reader")
st.write(
    "Upload an image or use your webcam. An AI **Random Forest Regressor**"
    " trained on 11 calibration levels analyzes the strip's color (RGB) to"
    " predict the cumulative dose."
)

# --- 1. DEFINE 11 CALIBRATION POINTS ---
# Simulating a dataset of 11 calibration standards (Dose vs. Mean RGB values)
# As H2S concentration/dose increases, the strip darkens (lower R, G, B values).
calibration_data = {
    "Dose_ppm_hr": [
        0.0,
        0.5,
        1.0,
        2.0,
        5.0,
        10.0,
        15.0,
        20.0,
        25.0,
        35.0,
        50.0,
    ],
    "Mean_R": [240, 225, 210, 195, 175, 150, 130, 110, 90, 70, 50],
    "Mean_G": [240, 220, 205, 185, 160, 135, 115, 95, 75, 55, 40],
    "Mean_B": [220, 200, 185, 165, 140, 115, 95, 75, 60, 45, 30],
}

df_calib = pd.DataFrame(calibration_data)

# Train the Random Forest Regressor on the fly
X_train = df_calib[["Mean_R", "Mean_G", "Mean_B"]]
y_train = df_calib["Dose_ppm_hr"]

rf_model = RandomForestRegressor(n_estimators=100, random_state=42)
rf_model.fit(X_train, y_train)

# Sidebar to view the 11 calibration points
with st.sidebar:
  st.header("Calibration Reference")
  st.write("Model trained on these 11 reference points:")
  st.dataframe(df_calib, hide_index=True)

# --- 2. INPUT IMAGE ---
option = st.radio("Choose image source:", ("Upload Image", "Use Webcam"))

image_source = None
if option == "Upload Image":
  image_source = st.file_uploader(
      "Choose an H2S strip image...", type=["jpg", "jpeg", "png"]
  )
else:
  image_source = st.camera_input("Take a picture of the test strip")

if image_source is not None:
  # Read image via OpenCV
  file_bytes = np.asarray(bytearray(image_source.read()), dtype=np.uint8)
  opencv_image = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)

  # Display captured/uploaded image
  st.image(
      cv2.cvtColor(opencv_image, cv2.COLOR_BGR2RGB),
      caption="Analyzed Strip",
      use_container_width=True,
  )

  # --- 3. FEATURE EXTRACTION (RGB) ---
  # Convert BGR to RGB
  rgb_image = cv2.cvtColor(opencv_image, cv2.COLOR_BGR2RGB)

  # Extract Region of Interest (ROI) from the center
  h, w, _ = rgb_image.shape
  roi = rgb_image[int(h * 0.4) : int(h * 0.6), int(w * 0.4) : int(w * 0.6)]

  # Calculate mean R, G, B values of the strip reactive zone
  mean_r = np.mean(roi[:, :, 0])
  mean_g = np.mean(roi[:, :, 1])
  mean_b = np.mean(roi[:, :, 2])

  # --- 4. PREDICTION ---
  # Reshape for sklearn model input
  input_features = np.array([[mean_r, mean_g, mean_b]])
  predicted_dose = rf_model.predict(input_features)[0]

  # --- 5. DISPLAY RESULTS ---
  st.markdown("---")
  st.subheader("Random Forest Analysis Results")

  col1, col2, col3 = st.columns(3)
  with col1:
    st.metric(
        label="Predicted Dose", value=f"{max(0.0, predicted_dose):.2f} ppm·hr"
    )
  with col2:
    st.metric(label="Extracted Mean RGB", value=f"({mean_r:.0f}, {mean_g:.0f}, {mean_b:.0f})")
  with col3:
    st.metric(label="Calibration Points", value="11 Levels")

  if predicted_dose > 20.0:
    st.error("⚠️ Warning: High cumulative H2S exposure detected!")
  else:
    st.success("✅ Exposure levels are within acceptable limits.")