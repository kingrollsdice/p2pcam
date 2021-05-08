from typing import Tuple

import cv2
import numpy as np


class MotionDetector:
    def __init__(self) -> None:
        self.last_frame = None

    """ Returns original frame and difference frame"""

    def detect(self, frame: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        last_frame = self.last_frame
        self.last_frame = frame
        if last_frame is None:
            return None, None

        # Difference between frame1(image) and frame2(image)
        diff = cv2.absdiff(last_frame, frame)

        # Converting color image to gray_scale image
        gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)

        # Converting gray scale image to GaussianBlur, so that change can be find easily
        blur = cv2.GaussianBlur(gray, (5, 5), 0)

        # If pixel value is greater than 20, it is assigned white(255) otherwise black
        _, thresh = cv2.threshold(blur, 20, 255, cv2.THRESH_BINARY)
        dilated = cv2.dilate(thresh, None, iterations=4)

        # finding contours of moving object
        contours, hirarchy = cv2.findContours(
            dilated, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE
        )

        # making rectangle around moving object
        for contour in contours:
            if cv2.contourArea(contour) < 1000:
                continue
            (x, y, w, h) = cv2.boundingRect(contour)
            cv2.rectangle(last_frame, (x, y), (x + w, y + h), (0, 255, 255), 2)

        return last_frame, thresh
