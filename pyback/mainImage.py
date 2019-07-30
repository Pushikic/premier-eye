import os
import asyncio
from colorama import Fore
import tracemalloc

import helpers.dateHelper as dh
import services.database_controller as db
import services.file_controller as file_controller
import helpers.timeChecker as timeChecker
import helpers.others as others


class MainClass(object):
    from settings import Settings
    cfg = Settings()  # единственный раз, когда мы создаем инстанс

    if cfg.ALGORITHM:
        from neural_network.maskCNN import Mask
        mask = Mask()
    else:
        from neural_network.imageAi import ImageAI
        imageAI = ImageAI()

    from neural_network.modules.decart import DecartCoordinates
    decart = DecartCoordinates()

    currentImageDir = os.path.join(os.getcwd(), cfg.IMAGE_DIR)

    def __init__(self):
        if self.cfg.checkOldProcessedFrames:
            processedFrames = dh.checkDateFile(self.cfg.DATE_FILE) 
        else:
            processedFrames = {}

        ioloop = asyncio.get_event_loop()
        ioloop.run_until_complete(self.mainPipeline(processedFrames))
        ioloop.close()

    def detectObject(self, numberOfCam, filenames, processedFrames):
        """
            Сакральный алгоритм:

            Глава I. Dictionary from images directory.
                Проходимся по папке с изображениями и цепляемся за головы. Головой в нашем случае назовем самое раннее
                изображение с каждой камеры. Как мы это сделаем? Добавим все в словарь типа 
                dict{numberOfCamera:arrayOfImages[numberOfCamera_image1, numberOfCamera_image2, .., numberOfCamera_imageN]}, 
                и отсортируем эти массивы по устареванию. Соответственно, нулевой элемент каждого массива - это голова.
            Глава II. Processed Frames.
                После успешного завершения алогритма мы добавляем название изображения в словарь processedFrames с такой же структурой, как и предыдущий.
                Если в processedFrames уже находится имя файла, которое мы взяли из словаря из прошлой главы, 
                то изображение уже обработано, и мы пропускаем его. После успешной обработки, мы записываем словарь в файл.
                Если стоит опция в настройках checkOldProcessedFrames, то при запуске программы, мы читаем из файла наш словарь, 
                соответственно, мы не обработаем файл, который был уже обработан при предыдущих запусках.
                Если у двух словарей идентичны массивы, ассоцирующуюся с одной камерой, то мы спим(спит поток:( )
            Глава III. То, чего нет.
                Потоки. В первоначальном задумке потоков(вероятнее всего, демонов) должно быть столько же, сколько и голов.
                И мы бы проходились по их чахлым телесам в n потоков. Но почему-то тензорфлоу(или керас) не может запуститься в мультитреде.
                Псевдокод многопоточки:
                    * Добавить к масиву потоков функцию со всем доступными аргументами в словаре №1
                    * После цикла пройтись по этому массиву и начать выполнение всех потоков 
                    - коммит #9106cbe
            Глава IV. лнениеАссин выпохронное.
                Дает меньший прирост, чем потоки. 
        """
        for filename in filenames:
            if numberOfCam not in processedFrames.keys():
                processedFrames.update({numberOfCam: []})

            if filename in processedFrames[numberOfCam]:
                if processedFrames[numberOfCam] == filenames:
                    print(f"Thread {numberOfCam} sleeping")
                    # time.sleep(2.5)  # засыпает поток исполнения
                continue  # если файлы еще есть, то переходим к следующему

            dateTime, numberOfCam = dh.parseFilename(filename, getNumberOfCamera=True)
            date, hours = dh.getDateOrHours(filename)

            inputFile = os.path.join(self.cfg.IMAGE_DIR, filename)
            outputFile = os.path.join(self.cfg.OUTPUT_DIR_MASKCNN, numberOfCam, date, hours, filename)
            print(f"Analyzing {inputFile}")

            imagesFromCurrentFrame = 0
            if self.cfg.ALGORITHM:  # Mask CNN
                detections, imagesFromCurrentFrame = self.mask.pipeline(inputFile, outputFile)
                rectCoordinates = detections['rois']
            else:  # image ai # эти алгоритмы всегда остают в нововведениях
                detections = self.imageAI.pipeline(inputFile, outputFile)
                rectCoordinates = others.parseImageAiData(detections)

            # car detector
            carNumber = None
            if self.cfg.CAR_NUMBER_DETECTOR:
                import neural_network.car_number as car_number
                if numberOfCam in [str(1), str(2)] and imagesFromCurrentFrame:  # если камера №2 или №1, то запускем тест на номера
                    objectImageDir = os.path.join(os.path.split(outputFile)[0], "objectsOn" + os.path.split(outputFile)[1])
                    for obj in os.listdir(objectImageDir):
                        name = str(obj).replace(" ", ",")
                        carNumber = car_number.detectCarNumber(os.path.join(objectImageDir, name))  # мы сохраняем файлы с найденными объектами, а потом юзаем их
                        # решение такое себе, т.к. мы обращаемся к долгой памяти
                        print(Fore.LIGHTBLUE_EX + str(carNumber))

            processedFrames[numberOfCam].append(filename)

            file_controller.writeInFile(self.cfg.DATE_FILE, str(processedFrames))  # будет стирать содержимое файла каждый кадр
     
            # DB
            if (self.cfg.loggingInDB):
                centerDown = self.decart.getCenterOfDownOfRectangle(rectCoordinates)  # массив массивов(массив координат центра нижней стороны прямоугольника у найденных объектов вида [[x1,y1],[x2,y2]..[xn,yn]])
                for i in range(0, len(rectCoordinates)):  # для каждого объекта, найденного на кадре
                    if carNumber == [] or carNumber == ['']:
                        carNumber = None
                    elif carNumber:
                        carNumber = carNumber[0]
                
                    db.writeInfoForObjectInDB(numberOfCam, dateTime, rectCoordinates[i], centerDown[i], carNumber)

            return detections
   
    def mainPipeline(self, processedFrames):
        while True:
            imagesForEachCamer = others.checkNewFile(self.currentImageDir)  # этим занимается главный поток
            for items in imagesForEachCamer.items():
                numberOfCam = items[0]
                filenames = items[1]
                self.detectObject(numberOfCam, filenames, processedFrames)
                from services.memory import display_top
                snapshot = tracemalloc.take_snapshot()
                display_top(snapshot)



if __name__ == "__main__":
    tracemalloc.start()
    p = MainClass()

