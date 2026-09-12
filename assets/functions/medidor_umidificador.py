import cv2
import numpy as np

def estimate_jar_height(image_path):
    image = cv2.imread(image_path)
    if image is None:
        print(f"Erro ao carregar a imagem: {image_path}")
        return

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    
    # --- 1. DETECÇÃO DO MARCADOR ARUCO ---
    aruco_dicts = {
        "DICT_4X4_50": cv2.aruco.DICT_4X4_50,
        "DICT_5X5_100": cv2.aruco.DICT_5X5_100,
        "DICT_6X6_250": cv2.aruco.DICT_6X6_250,
        "DICT_ARUCO_ORIGINAL": cv2.aruco.DICT_ARUCO_ORIGINAL
    }

    aruco_corners_found = None
    for name, dict_id in aruco_dicts.items():
        aruco_dict = cv2.aruco.getPredefinedDictionary(dict_id)
        aruco_params = cv2.aruco.DetectorParameters()
        detector = cv2.aruco.ArucoDetector(aruco_dict, aruco_params)
        corners, ids, rejected = detector.detectMarkers(gray)
        
        if corners:
            aruco_corners_found = corners[0][0]
            print(f"[OK] ArUco detectado ({name})")
            break

    if aruco_corners_found is None:
        print("ArUco não detectado. Ajuste a iluminação ou use cv2.equalizeHist(gray).")
        return

    # Largura do ArUco em pixels
    top_left, top_right = aruco_corners_found[0], aruco_corners_found[1]
    w_aruco_px = np.linalg.norm(top_right - top_left)
    cv2.polylines(image, [aruco_corners_found.astype(int)], True, (0, 255, 0), 2)

    # --- 2. DETECÇÃO DO FRASCO ---
    blurred = cv2.GaussianBlur(gray, (9, 9), 0)
    edges = cv2.Canny(blurred, 40, 120)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=4)
    
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    best_jar = None
    max_area = 0

    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        area = w * h
        # Filtro de proporção (h/w) e tamanho para ignorar ruídos e fios
        if w > 0:
            aspect_ratio = h / float(w)
            if area > 2000 and 0.8 < aspect_ratio < 2.5:
                if area > max_area:
                    max_area = area
                    best_jar = (x, y, w, h)

    if not best_jar:
        print("Frasco não detectado pelos contornos.")
        return

    x, y, w_jar_px, h_jar_px = best_jar

    # --- 3. CÁLCULO DE CÂMERA (PINHOLE MODEL) ---
    # f = 3.2 / ( (3.0/W_aruco) - (6.4/W_jar) )
    term_aruco = 3.0 / w_aruco_px
    term_jar = 6.4 / w_jar_px
    
    # Prevenção de divisão por zero ou matemática impossível (frasco parecendo menor que deveria)
    if term_aruco <= term_jar:
        print("Erro óptico: O frasco parece estar mais longe que a parede nas medições de pixel.")
        return
        
    focal_length_px = 3.2 / (term_aruco - term_jar)
    
    # Distância da câmera até a parede preta e até o frasco
    z_wall_cm = (focal_length_px * 3.0) / w_aruco_px
    z_jar_cm = z_wall_cm - 3.2 
    
    # Tamanho do pixel na profundidade do frasco
    px_per_cm_jar = focal_length_px / z_jar_cm
    
    # Altura real do frasco
    height_jar_cm = h_jar_px / px_per_cm_jar

    # --- 4. EXIBIÇÃO DE TELEMETRIA ---
    print(f"\n--- TELEMETRIA ÓPTICA ---")
    print(f"Distância Focal (f): {focal_length_px:.2f} px")
    print(f"Profundidade da Parede (Z_wall): {z_wall_cm:.2f} cm")
    print(f"Profundidade do Frasco (Z_jar): {z_jar_cm:.2f} cm")
    print(f"Altura do Frasco: {height_jar_cm:.2f} cm")

    # Desenhar UI na imagem
    cv2.rectangle(image, (x, y), (x + w_jar_px, y + h_jar_px), (255, 0, 0), 2)
    
    ui_text = [
        f"f (lente): {focal_length_px:.0f}px",
        f"Z parede: {z_wall_cm:.1f}cm",
        f"Z frasco: {z_jar_cm:.1f}cm",
        f"Alt. Pote: {height_jar_cm:.2f}cm"
    ]
    
    for i, text in enumerate(ui_text):
        cv2.putText(image, text, (10, 30 + (i * 25)), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

    cv2.imshow("Telemetria e Medicao", image)
    cv2.waitKey(0)
    cv2.destroyAllWindows()

estimate_jar_height("assets/pictures/kampu_1788448322.jpg")