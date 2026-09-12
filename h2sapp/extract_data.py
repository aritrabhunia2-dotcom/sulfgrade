import os
import re
import cv2
import numpy as np
import pandas as pd


def normalize_lighting(image_rgb):
  """Applies Gray World Algorithm to neutralize color casts

  caused by different lighting (e.g., warm indoor bulbs vs daylight).
  """
  result = image_rgb.astype(np.float32)

  # Calculate average values for Red, Green, and Blue channels
  mean_r = np.mean(result[:, :, 0])
  mean_g = np.mean(result[:, :, 1])
  mean_b = np.mean(result[:, :, 2])

  # Prevent division by zero
  if mean_r == 0 or mean_g == 0 or mean_b == 0:
    return image_rgb

  # Find the overall gray mean
  mean_gray = (mean_r + mean_g + mean_b) / 3.0

  # Scale each channel to match the gray balance
  result[:, :, 0] = result[:, :, 0] * (mean_gray / mean_r)
  result[:, :, 1] = result[:, :, 1] * (mean_gray / mean_g)
  result[:, :, 2] = result[:, :, 2] * (mean_gray / mean_b)

  # Clip values back to valid 0-255 image range and convert back to uint8
  result = np.clip(result, 0, 255).astype(np.uint8)
  return result


dataset_path = "dataset"
data = []

print(
    "Scanning dataset folders and extracting lighting-corrected RGB values..."
)

# Check if dataset folder exists
if not os.path.exists(dataset_path):
  print(
      f"❌ Error: The '{dataset_path}' folder does not exist. Please create it"
      " first."
  )
else:
  # Loop through each dose subfolder
  for dose_folder in os.listdir(dataset_path):
    folder_full_path = os.path.join(dataset_path, dose_folder)

    if os.path.isdir(folder_full_path):
      dose_match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*ppm", dose_folder,
                                flags=re.IGNORECASE)
      if dose_match is None:
        continue  # Skip folders that don't use the expected dose naming
      dose_value = float(dose_match.group(1))

      # Loop through images inside the dose folder
      for img_name in os.listdir(folder_full_path):
        img_path = os.path.join(folder_full_path, img_name)
        if not img_name.lower().endswith((".jpg", ".jpeg", ".png", ".bmp",
                                          ".tif", ".tiff", ".webp")):
          continue
        img = cv2.imread(img_path)

        if img is not None:
          # Convert BGR to RGB
          rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

          # ---> FIX: Apply lighting correction here to match app.py! <---
          corrected_img = normalize_lighting(rgb_img)

          # Extract Region of Interest (ROI) from the center (20% box) of the corrected image
          h, w, _ = corrected_img.shape
          roi = corrected_img[
              int(h * 0.4) : int(h * 0.6), int(w * 0.4) : int(w * 0.6)
          ]

          # Get mean RGB values of the center strip area
          mean_r = np.mean(roi[:, :, 0])
          mean_g = np.mean(roi[:, :, 1])
          mean_b = np.mean(roi[:, :, 2])

          # Store data row
          data.append(
              {
                  "Dose_ppm_hr": dose_value,
                  "Mean_R": mean_r,
                  "Mean_G": mean_g,
                  "Mean_B": mean_b,
              }
          )
          print(
              f"Processed: {dose_folder}/{img_name} -> Corrected RGB"
              f" ({mean_r:.1f}, {mean_g:.1f}, {mean_b:.1f})"
          )

  if len(data) > 0:
    # Save everything into a CSV file
    df = pd.DataFrame(data)
    df.to_csv("h2s_training_data.csv", index=False)
    print(
        "\nSUCCESS: 'h2s_training_data.csv' generated with lighting correction!"
    )
  else:
    print("\n❌ No valid images found inside the dataset subfolders.")