"""
ML Model for Route Optimization
"""
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import StandardScaler
import pickle
import os

class RouteOptimizationModel:
    def __init__(self):
        self.model = RandomForestRegressor(n_estimators=100, random_state=42)
        self.scaler = StandardScaler()
        self.is_trained = False
        self._load_or_train()
    
    def _generate_training_data(self, n_samples=1000):
        X = []
        y = []
        
        for _ in range(n_samples):
            distance = np.random.uniform(0.5, 50)
            time_of_day = np.random.uniform(8, 18)
            is_vip = np.random.choice([0, 1], p=[0.7, 0.3])
            traffic_factor = np.random.uniform(0.8, 1.5)
            
            optimal_score = (
                distance * 0.4 +
                abs(time_of_day - 12) * 0.2 +
                (1 - is_vip) * 10 +
                traffic_factor * 5
            )
            
            X.append([distance, time_of_day, is_vip, traffic_factor])
            y.append(optimal_score)
        
        return np.array(X), np.array(y)
    
    def _load_or_train(self):
        model_path = 'route_model.pkl'
        scaler_path = 'route_scaler.pkl'
        
        if os.path.exists(model_path) and os.path.exists(scaler_path):
            try:
                with open(model_path, 'rb') as f:
                    self.model = pickle.load(f)
                with open(scaler_path, 'rb') as f:
                    self.scaler = pickle.load(f)
                self.is_trained = True
                return
            except:
                pass
        
        X, y = self._generate_training_data()
        X_scaled = self.scaler.fit_transform(X)
        self.model.fit(X_scaled, y)
        self.is_trained = True
        
        try:
            with open(model_path, 'wb') as f:
                pickle.dump(self.model, f)
            with open(scaler_path, 'wb') as f:
                pickle.dump(self.scaler, f)
        except:
            pass
    
    def predict_score(self, distance, time_of_day, is_vip, traffic_factor=1.0):
        if not self.is_trained:
            return distance
        
        features = np.array([[distance, time_of_day, is_vip, traffic_factor]])
        features_scaled = self.scaler.transform(features)
        score = self.model.predict(features_scaled)[0]
        
        return max(score, 0)
    
    def calculate_optimal_weights(self, client_data):
        scores = []
        for client in client_data:
            score = self.predict_score(
                client.get('distance', 1),
                client.get('time', 12),
                1 if client.get('priority') == 'VIP' else 0,
                client.get('traffic', 1.0)
            )
            scores.append(score)
        
        return scores

model_instance = RouteOptimizationModel()

def get_model():
    return model_instance

