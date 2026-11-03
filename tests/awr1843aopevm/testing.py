import json
from pprint import pprint
import math
class Frame():
    def __init__(self, data):
        self.s_time = data["time_s"]
        self.point = Point(data["points"][0]) #make dynamic


class Point():
    def __init__(self, data):
        self.x = data['x']
        self.y = data['y']
        #self.z = data['z'] #ignored based on distance hypothesis

class Calculate():
    def __init__(self):
        with open("data_clean.json", "r") as f:
            self.data = json.load(f)["frames"]
            f.close()


    def identify(self):
        #doppler ad_hoc calc based from own speed
        pass

    def doppler(self)

    def movement(self):
        self.frame1 = Frame(self.data[0])
        self.frame2 = Frame(self.data[1])
        #make dynamic you wanker

        temp = math.sqrt(math.pow(frame2.point.x - frame1.point.x, 2) + math.pow(frame2.point.y - frame1.point.y, 2))

        return temp / (frame2.s_time - frame1.s_time)

    def distance(self):
        # y is frontal distance, x is lateral distance, z is height (HYPOTHESIS)
        pass

if __name__ == '__main__':
    calculate = Calculate()
