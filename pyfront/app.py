from application import createApp
import Config as cfg

app = createApp()

if __name__ == "__main__":  # хм это же мейн
    app.run(cfg.FLASK_RUN_HOST , debug=True)
