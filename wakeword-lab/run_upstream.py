"""Run pinned upstream, avoiding meaningless ROC when no ambient data exists."""
import runpy


def ambient_guard(original):
    def guarded(config, folder, processor, *args, **kwargs):
        ambient = kwargs.get("ambient_set", "testing_ambient")
        if processor.get_mode_size(ambient) == 0:
            print("ROC ambiente omitida: não há gravações ambiente; não interpretar como 0 falsos/hora.", flush=True)
            return None
        return original(config, folder, processor, *args, **kwargs)
    return guarded


if __name__ == "__main__":
    import microwakeword.test as upstream_test
    upstream_test.tflite_streaming_model_roc = ambient_guard(upstream_test.tflite_streaming_model_roc)
    runpy.run_module("microwakeword.model_train_eval", run_name="__main__")
