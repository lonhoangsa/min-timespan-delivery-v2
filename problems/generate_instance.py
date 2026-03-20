"""
Script để sinh instance data cho PVRPWDP problem.
Dựa trên logic từ generator.py trong rl4co.

Format output giống file 20.20.1.txt:
- Depot tại (0, 0)
- Customers với tọa độ random trong khoảng [-map_size/2, +map_size/2]
- Demand phụ thuộc vào vị trí (near/far drone radius)
"""

import random
import math
import argparse
import os
import time
from datetime import datetime


class InstanceGenerator:
    def __init__(
        self,
        num_customers=20,
        num_trucks=1,
        num_drones=0,
        map_size=35000.0,  # meters (35 km = 35000 m)
        drone_endurance=700.0,  # seconds
        drone_speed=31.2928,  # m/s (112 km/h)
        truck_speed=15.6464,  # m/s (50 km/h)
        p_near=0.5,  # xác suất customer nằm trong bán kính drone
        p_light_near=0.80,  # xác suất demand nhẹ (< 1.25) khi ở vùng near
        p_light_far=0.50,  # xác suất demand nhẹ khi ở vùng far
        min_demand=0.1,  # kg
        light_max_demand=1.25,  # kg (ngưỡng demand nhẹ)
        heavy_max_demand=49.0,  # kg
        seed=None,
    ):
        """
        Parameters:
        -----------
        num_customers : int
            Số lượng khách hàng
        num_trucks : int
            Số lượng xe tải
        num_drones : int
            Số lượng drone
        map_size : float
            Kích thước bản đồ (meters), tọa độ sẽ random trong [-map_size/2, +map_size/2]
        drone_endurance : float
            Thời gian bay tối đa của drone (seconds)
        drone_speed : float
            Tốc độ drone (m/s)
        truck_speed : float
            Tốc độ xe tải (m/s)
        p_near : float
            Xác suất customer nằm trong bán kính bay của drone (0.0 - 1.0)
        p_light_near : float
            Xác suất demand nhẹ (< light_max_demand) khi customer ở vùng near (0.0 - 1.0)
            Ví dụ: 0.80 = 80% nhẹ, 20% nặng
        p_light_far : float
            Xác suất demand nhẹ khi customer ở vùng far (0.0 - 1.0)
        min_demand : float
            Demand tối thiểu (kg)
        light_max_demand : float
            Ngưỡng phân biệt demand nhẹ/nặng (kg)
        heavy_max_demand : float
            Demand tối đa (kg)
        seed : int, optional
            Random seed để tái tạo kết quả
        """
        self.num_customers = num_customers
        self.num_trucks = num_trucks
        self.num_drones = num_drones
        self.map_size = map_size
        self.drone_endurance = drone_endurance
        self.drone_speed = drone_speed
        self.truck_speed = truck_speed
        self.p_near = p_near
        self.p_light_near = p_light_near
        self.p_light_far = p_light_far
        self.min_demand = min_demand
        self.light_max_demand = light_max_demand
        self.heavy_max_demand = heavy_max_demand
        
        if seed is not None:
            random.seed(seed)
        
        # Tính bán kính drone (meters)
        # drone có thể bay tới điểm và quay về = endurance
        # => khoảng cách tối đa = (endurance / 2) * speed
        self.drone_radius_m = (self.drone_endurance / 2.0) * self.drone_speed
        
        print(f"=== Instance Generator Config ===")
        print(f"Customers: {self.num_customers}")
        print(f"Trucks: {self.num_trucks}, Drones: {self.num_drones}")
        print(f"Map size: {self.map_size} m (range: [-{self.map_size/2}, +{self.map_size/2}])")
        print(f"Drone endurance: {self.drone_endurance} sec")
        print(f"Drone speed: {self.drone_speed} m/s, Truck speed: {self.truck_speed} m/s")
        print(f"Drone radius: {self.drone_radius_m:.2f} m")
        print(f"Near region probability: {self.p_near*100:.1f}%")
        print(f"Light demand (near) probability: {self.p_light_near*100:.1f}%")
        print(f"Light demand (far) probability: {self.p_light_far*100:.1f}%")
        print(f"Demand range: [{self.min_demand}, {self.light_max_demand}] (light), [{self.light_max_demand}, {self.heavy_max_demand}] (heavy)")
        print()
    
    def _distance(self, x1, y1, x2, y2):
        """Tính khoảng cách Euclidean (meters)"""
        return math.sqrt((x1 - x2)**2 + (y1 - y2)**2)
    
    def _sample_location_near(self, depot_x, depot_y):
        """Sample location trong vòng tròn bán kính drone quanh depot"""
        while True:
            # Polar coordinates
            rho = self.drone_radius_m * math.sqrt(random.random())
            theta = 2 * math.pi * random.random()
            
            x = depot_x + rho * math.cos(theta)
            y = depot_y + rho * math.sin(theta)
            
            # Kiểm tra trong giới hạn bản đồ
            half_size = self.map_size / 2.0
            if -half_size <= x <= half_size and -half_size <= y <= half_size:
                return x, y
    
    def _sample_location_far(self):
        """Sample location uniform trên toàn bộ bản đồ"""
        half_size = self.map_size / 2.0
        x = random.uniform(-half_size, half_size)
        y = random.uniform(-half_size, half_size)
        return x, y
    
    def _sample_demand(self, x, y, depot_x, depot_y):
        """
        Sample demand dựa trên vị trí:
        - Near (trong bán kính drone):
            + p_light_near: demand trong [min_demand, light_max_demand]
            + (1 - p_light_near): demand trong [light_max_demand, heavy_max_demand]
        - Far (ngoài bán kính):
            + p_light_far: demand trong [min_demand, light_max_demand]
            + (1 - p_light_far): demand trong [light_max_demand, heavy_max_demand]
        """
        dist = self._distance(x, y, depot_x, depot_y)
        is_near = dist <= self.drone_radius_m
        
        if is_near:
            if random.random() < self.p_light_near:
                # Light demand
                demand = random.uniform(self.min_demand, self.light_max_demand)
            else:
                # Heavy demand
                demand = random.uniform(self.light_max_demand, self.heavy_max_demand)
        else:
            # Far region: 50% light, 50% heavy
            if random.random() < self.p_light_far:
                # Light demand
                demand = random.uniform(self.min_demand, self.light_max_demand)
            else:
                # Heavy demand
                demand = random.uniform(self.light_max_demand, self.heavy_max_demand)
        
        return demand
    
    def generate(self):
        """
        Sinh một instance và trả về dict chứa thông tin.
        
        Returns:
        --------
        dict với keys:
            - depot: (x, y)
            - customers: list of dicts với keys: x, y, dronable, demand
        """
        # Depot tại (0, 0)
        depot_x, depot_y = 0.0, 0.0
        
        customers = []
        for i in range(self.num_customers):
            # Sample location
            if random.random() < self.p_near:
                x, y = self._sample_location_near(depot_x, depot_y)
            else:
                x, y = self._sample_location_far()
            
            # Sample demand
            demand = self._sample_demand(x, y, depot_x, depot_y)
            
            # Dronable = 1 (tất cả customer đều có thể được drone phục vụ)
            dronable = 1
            
            customers.append({
                'x': x,
                'y': y,
                'dronable': dronable,
                'demand': demand,
            })
        
        return {
            'depot': (depot_x, depot_y),
            'customers': customers,
        }
    
    def save_to_file(self, instance, filename):
        """
        Lưu instance ra file txt theo format giống 20.20.1.txt
        
        Parameters:
        -----------
        instance : dict
            Dict trả về từ generate()
        filename : str
            Tên file output
        """
        with open(filename, 'w') as f:
            # Header
            f.write(f"trucks_count {self.num_trucks}\n")
            f.write(f"drones_count {self.num_drones}\n")
            f.write(f"customers {self.num_customers}\n")
            f.write(f"depot {instance['depot'][0]} {instance['depot'][1]}\n")
            
            # Customer header
            f.write(f"{'Coordinate X':<20} {'Coordinate Y':<20} Dronable Demand\n")
            
            # Customers
            for customer in instance['customers']:
                x = customer['x']
                y = customer['y']
                dronable = customer['dronable']
                demand = customer['demand']
                
                f.write(f"{x:<20} {y:<20} {dronable:<9} {demand}\n")
        
        print(f"Instance saved to: {filename}")
        print(f"Total customers: {len(instance['customers'])}")
        
        # Statistics
        demands = [c['demand'] for c in instance['customers']]
        depot_x, depot_y = instance['depot']
        distances = [self._distance(c['x'], c['y'], depot_x, depot_y) for c in instance['customers']]
        near_count = sum(1 for d in distances if d <= self.drone_radius_m)
        light_count = sum(1 for d in demands if d < self.light_max_demand)
        
        print(f"  - Near region (<={self.drone_radius_m:.2f} m): {near_count}/{self.num_customers} ({near_count/self.num_customers*100:.1f}%)")
        print(f"  - Light demand (<{self.light_max_demand} kg): {light_count}/{self.num_customers} ({light_count/self.num_customers*100:.1f}%)")
        print(f"  - Demand: min={min(demands):.2f}, max={max(demands):.2f}, avg={sum(demands)/len(demands):.2f} kg")
        print(f"  - Distance: min={min(distances):.2f}, max={max(distances):.2f}, avg={sum(distances)/len(distances):.2f} m")


def main():
    # ============================================================
    # CẤU HÌNH - THAY ĐỔI CÁC BIẾN NÀY THEO Ý BẠN
    # ============================================================
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Generate instances for PVRPWDP")
    parser.add_argument("--start-number", type=int, default=0,
                        help="Starting number for file naming (default: 0)")
    parser.add_argument("--batch-size", type=int, default=4000,
                        help="Number of instances to generate (default: 4000)")
    args = parser.parse_args()
    
    # --- Batch Generation Mode ---
    # Để sinh nhiều file: đặt batch_size = số file muốn sinh (ví dụ: 20)
    # Để sinh 1 file đơn: đặt batch_size = None
    batch_size = args.batch_size  # Có thể pass từ command line
    start_number = args.start_number  # Có thể pass từ command line
    
    # --- Output Config ---
    output_folder = "data"  # <--- Tên folder chứa các file txt (trong genData/)
    single_output = "instance.txt"  # <--- Tên file nếu chỉ sinh 1 file (khi batch_size = None)
    
    # --- Advanced Config ---
    p_near = 0.8                 # Xác suất customer nằm trong vùng near (0.0 - 1.0)
    p_light_near = 0.80          # Xác suất demand nhẹ trong vùng near (0.0 - 1.0)
    p_light_far = 0.50           # Xác suất demand nhẹ trong vùng far (0.0 - 1.0)
    drone_endurance = 700.0      # Thời gian bay tối đa của drone (giây)
    
    # Tính seed theo format: abcdefghij
    # ab = 2 chữ số cuối của năm
    # cd = 2 chữ số tháng (01-12)
    # ef = 2 chữ số ngày (01-31)
    # ghij = toàn bộ số giây hiện tại trong ngày (0-86399)
    now = datetime.now()
    year_2digit = now.year % 100
    month = now.month
    day = now.day
    seconds_in_day = now.hour * 3600 + now.minute * 60 + now.second
    
    seed = int(f"{year_2digit:02d}{month:02d}{day:02d}{seconds_in_day:05d}")
    random.seed(seed)
    print(f"Random seed: {seed} (YY={year_2digit:02d}, MM={month:02d}, DD={day:02d}, SS={seconds_in_day:05d})\n")
    
    # ============================================================
    # CODE XỬ LÝ - KHÔNG CẦN THAY ĐỔI PHẦN NÀY
    # ============================================================
    
    # Check if batch generation
    if batch_size is not None:
        # Batch generation mode
        n = batch_size
        
        # Create output directory inside genData folder
        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_dir = os.path.join(script_dir, output_folder)
        os.makedirs(output_dir, exist_ok=True)
        
        print(f"\n{'='*60}")
        print(f"BATCH GENERATION MODE")
        print(f"{'='*60}")
        print(f"Generating {n} instances...")
        print(f"Output directory: {output_dir}")
        print(f"Filename pattern: instance{start_number}.txt to instance{start_number + n - 1}.txt")
        print(f"{'='*60}\n")
        
        # Generate n instances
        for i in range(start_number, start_number + n):
            # Random parameters for each instance
            num_customers = random.randint(20, 100)  # Random từ 20 tới 100 nodes
            map_size = random.uniform(10000.0, 40000.0)  # Random từ 10km tới 40km
            
            # Determine trucks and drones based on num_customers
            if num_customers <= 40:
                num_trucks = random.randint(2, 3)
                num_drones = random.randint(2, 3)
            elif num_customers < 81:  # 40 < num_customers < 81
                num_trucks = random.randint(3, 5)
                num_drones = random.randint(3, 5)
            else:  # num_customers >= 81
                num_trucks = random.randint(4, 6)
                num_drones = random.randint(4, 6)
            
            # Create generator with randomized parameters
            generator = InstanceGenerator(
                num_customers=num_customers,
                num_trucks=num_trucks,
                num_drones=num_drones,
                map_size=map_size,
                p_near=p_near,
                p_light_near=p_light_near,
                p_light_far=p_light_far,
                drone_endurance=drone_endurance,
                seed=None,  # Don't set seed in generator, already set globally
            )
            
            filename = f"instance{i}.txt"
            filepath = os.path.join(output_dir, filename)
            
            print(f"[{i - start_number + 1}/{n}] Generating {filename}...")
            print(f"  Parameters: {num_customers} customers, {num_trucks} trucks, {num_drones} drones, {map_size:.0f}m map")
            instance = generator.generate()
            generator.save_to_file(instance, filepath)
            print()
        
        print(f"{'='*60}")
        print(f"[OK] Successfully generated {n} instances in: {output_dir}")
        print(f"{'='*60}")
    else:
        # Single generation mode
        num_customers = random.randint(20, 100)
        map_size = random.uniform(10000.0, 40000.0)
        
        if num_customers <= 40:
            num_trucks = random.randint(2, 3)
            num_drones = random.randint(2, 3)
        elif num_customers < 81:
            num_trucks = random.randint(3, 5)
            num_drones = random.randint(3, 5)
        else:
            num_trucks = random.randint(4, 6)
            num_drones = random.randint(4, 6)
        
        generator = InstanceGenerator(
            num_customers=num_customers,
            num_trucks=num_trucks,
            num_drones=num_drones,
            map_size=map_size,
            p_near=p_near,
            p_light_near=p_light_near,
            p_light_far=p_light_far,
            drone_endurance=drone_endurance,
            seed=None,  # Don't set seed in generator, already set globally
        )
        
        instance = generator.generate()
        generator.save_to_file(instance, single_output)


if __name__ == '__main__':
    main()
