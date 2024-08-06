import numpy as np
from enum import Enum
from scipy import stats
import pickle
import random
import time


class CpAlgorithms(Enum):
    LAC = "LAC"
    APS = "APS"
    RAPS = "RAPS"


class ConformalPredictor:
    def __init__(self, calibrator="RAPS", alpha=0.2, load_from_file=None):
        self.is_calibrated = False
        if load_from_file:
            self.__load_predictor(load_from_file)
        else:
            self.alpha: float = alpha
            self.calibrator_algo: CpAlgorithms = self.check_calibration_method(
                calibrator
            )
            self.qhat: float = None
            self.reg_vec: np.array[float] = None

    def check_calibration_method(self, calibrator: str) -> CpAlgorithms:
        try:
            return CpAlgorithms(calibrator)
        except ValueError:
            raise ValueError(f"Calibrator {calibrator} is not valid")

    def calibrate(self, smx_out, label):
        """
        Calibrates the conformal prediction models using the given calibration data and labels.

        Args:
            smx_out (numpy.ndarray) shape: [samples, labels]: Softmax output for calibration
            label (numpy.array) shape: [samples]: The corresponding label indices.

        Raises:
            ValueError: If the length of `smx_out` is not equal to the length of `label`.
            NotImplementedError: If the calibration algorithm is not implemented.

        Returns:
            None
        """
        # Check input shape
        if len(smx_out) != len(label):
            raise ValueError(
                f"Calibration data and labels must have same length: {len(smx_out)} != {len(label)}"
            )

        # Esnure data consistency
        smx_out = np.array(smx_out)
        label = np.array(label)

        match self.calibrator_algo:
            case CpAlgorithms.LAC:
                self.__LACcalibrator(smx_out, label)
            case CpAlgorithms.APS:
                self.__APScalibrator(smx_out, label)
            case CpAlgorithms.RAPS:
                self.__RAPScalibrator(smx_out, label)
            case _:
                raise NotImplementedError(
                    f"Calibration for {self.calibrator_algo.name} is not yet implemented"
                )
        self.is_calibrated = True

    def predict(self, class_predictions: np.array) -> np.array:
        """
        Predicts the class labels for the given class predictions

        Args:
            class_predictions (np.array) either batch:[samples,labels] or single:[labels]: Model softmax predcition for labels

        Raises:
            RuntimeError: If the models is not calibrated.
            NotImplementedError: If the prediction algorithm is not implemented.

        Returns:
            np.array like input shape: Conformalized prediction sets.
        """

        if not self.is_calibrated:
            raise RuntimeError(
                "Conformal Predictor must be calibrated before prediction"
            )

        # Ensure data consistency
        class_predictions = np.array(class_predictions)

        # Match structure in case of single sample (1D) input
        reshaped = False
        if len(class_predictions.shape) == 1:
            class_predictions = class_predictions[np.newaxis, :]
            reshaped = True

        match self.calibrator_algo:
            case CpAlgorithms.LAC:
                result = self.__LACprediction(class_predictions)
            case CpAlgorithms.APS:
                result = self.__APSprediction(class_predictions)
            case CpAlgorithms.RAPS:
                result = self.__RAPSprediction(class_predictions)
            case _:
                raise NotImplementedError(
                    f"Prediction for {self.calibrator_algo.name} is not yet implemented"
                )
        return result
        # return result if not reshaped else result[0]

    def store_predictor(self, path: str) -> None:
        with open(path, "wb") as outp:
            pickle.dump(self, outp, pickle.HIGHEST_PROTOCOL)

    def __load_predictor(self, path: str) -> None:
        if self.is_calibrated:
            print("Warning, already calibrated predictor is being overwritten")
        try:
            with open(path, "rb") as input:
                loaded_predictor = pickle.load(input)
                self.alpha = loaded_predictor.alpha
                self.calibrator_algo = loaded_predictor.calibrator_algo
                self.qhat = loaded_predictor.qhat
                self.is_calibrated = loaded_predictor.is_calibrated
                self.reg_vec = loaded_predictor.reg_vec
            print(
                f"Loaded Predictor from file: \n  calibrator_algo = {self.calibrator_algo}\n  alpha = {self.alpha}\n  qhat = {self.qhat:.4f}"
            )
        except Exception as error:
            print("An exception occurred:", type(error).__name__)
            print(error)

    def __LACcalibrator(self, smx_out, label_idx):
        n = len(smx_out)
        cal_scores = (
            1 - smx_out[np.arange(n), label_idx.astype(int)]
        )  # for all calibration data 1-softmax output
        q_level = np.ceil((n + 1) * (1 - self.alpha)) / n
        print("Effektive q_level:", q_level)
        self.qhat = np.quantile(cal_scores, q_level, interpolation="higher")
        print("Calibrated qhat:", self.qhat)

    def __LACprediction(self, class_predictions):
        cp_predictions = (class_predictions.astype(np.float32) >= self.qhat).astype(int)
        return cp_predictions

    def __APScalibrator(self, smx_out, label_idx):
        n = len(smx_out)

        sorted_smx_idx = (np.argsort(smx_out, axis=-1)[:, ::-1]).astype(int)
        sorted_truelabel_idx = (
            np.where(sorted_smx_idx == label_idx[:, np.newaxis])[1]
        ).astype(int)
        # Sort softmax output in descending order
        sorted_smx_scores = np.take_along_axis(smx_out, sorted_smx_idx, axis=-1)
        cal_scores = np.cumsum(sorted_smx_scores, axis=-1)[
            np.arange(n), sorted_truelabel_idx
        ]

        q_level = np.ceil((n + 1) * (1 - self.alpha)) / n
        self.qhat = np.quantile(cal_scores, q_level, interpolation="higher")

    def __APSprediction(self, class_predictions):
        sorted_smx_idx = np.argsort(class_predictions, axis=-1)[:, ::-1]

        # Get result as first index where the cumulative sum is greater than qhat
        result = (
            np.cumsum(
                np.take_along_axis(class_predictions, sorted_smx_idx, axis=-1), axis=-1
            )
            > self.qhat
        )

        # If all values are False, return the highest possible index -> all labels within set
        max_idx = np.where(
            result.any(axis=-1), result.argmax(axis=-1), result.shape[-1] - 1
        )

        output = np.zeros_like(class_predictions)
        for j, idx_set in enumerate(sorted_smx_idx):
            # Check if fist idx already fullfilled the qhat condition add 1 for indexing otherwise take all samples up to condition
            cur_max = max_idx[j] + 1 if max_idx[j] == 0 else max_idx[j]
            output[j, idx_set[:cur_max]] = 1
        return output

    def __RAPScalibrator(self, smx_out, label_idx, reg_k=2, reg_lam=0.06):
        n = len(smx_out)

        # Compute penalty vector for set regularization
        self.reg_vec = np.array(
            reg_k
            * [
                0,
            ]
            + (smx_out.shape[1] - reg_k)
            * [
                reg_lam,
            ]
        )[np.newaxis, :]

        sorted_smx_idx = (np.argsort(smx_out, axis=-1)[:, ::-1]).astype(int)
        sorted_truelabel_idx = (
            np.where(sorted_smx_idx == label_idx[:, np.newaxis])[1]
        ).astype(int)
        reg_sorted_smx_scores = (
            np.take_along_axis(smx_out, sorted_smx_idx, axis=-1) + self.reg_vec
        )
        cal_scores = np.cumsum(reg_sorted_smx_scores, axis=-1)[
            np.arange(n), sorted_truelabel_idx
        ]  # - np.random.rand(n)*reg_sorted_smx_scores[np.arange(n),sorted_truelabel_idx] # TODO: check randomization

        q_level = np.ceil((n + 1) * (1 - self.alpha)) / n
        self.qhat = np.quantile(cal_scores, q_level, interpolation="higher")

    def __RAPSprediction(self, class_predictions):
        n = len(class_predictions)
        sorted_smx_idx = np.argsort(class_predictions, axis=-1)[:, ::-1]
        reg_sorted_smx_scores = (
            np.take_along_axis(class_predictions, sorted_smx_idx, axis=-1)
            + self.reg_vec
        )
        reg_sorted_cumsum = np.cumsum(
            reg_sorted_smx_scores, axis=-1
        )  # - np.random.rand(n,1)*reg_sorted
        result = reg_sorted_cumsum > self.qhat
        # If all values are False, return the highest possible index
        max_idx = np.where(
            result.any(axis=-1), result.argmax(axis=-1), result.shape[-1] - 1
        )

        output = np.zeros_like(class_predictions)
        for j, idx_set in enumerate(sorted_smx_idx):
            # Check if fist idx already fullfilled the qhat condition add 1 for indexing otherwise take all samples up to condition
            cur_max = max_idx[j] + 1 if max_idx[j] == 0 else max_idx[j]
            output[j, idx_set[:cur_max]] = 1
        return output


class PredictionSolver:
    def __init__(
        self,
        kernel_size: int = 10,
        solver_strategie: str = "mode",
        solve_online: bool = False,
        filter_single_sets: bool = False,
        reject_setsize: int = 4,
        buffer_size_accepted_labels: int = 5,  # in samples
        buffer_time_till_timeout: int = 10,  # in seconds
    ):
        self.kernel_size = kernel_size
        self.solver_strategie = solver_strategie
        self.solve_online = solve_online
        self.filter_single_sets = filter_single_sets
        self.reject_setsize = reject_setsize

        self._last_solved_accepted = []
        self.buffer_size_accepted_labels = buffer_size_accepted_labels
        self.buffer_time_till_timeout = buffer_time_till_timeout

        if self.solve_online:
            self._last_solved = []
            self._last_val = []

    def solve(self, prediction):
        # TODO: check input sizes

        # Reject predictions with more labels as set in self.reject_samples
        if self.reject_setsize is not None:
            num_labels = np.sum(prediction, axis=-1)
            prediction = np.array(
                [
                    (
                        prediction_set
                        if num_labels[idx] < self.reject_setsize
                        else np.zeros_like(prediction_set)
                    )
                    for idx, prediction_set in enumerate(prediction)
                ]
            )

        # Run solving
        if self.solve_online:
            return self.__online_solver(prediction[0])
        else:
            return self.__offline_solver(prediction)

    def __online_solver(self, prediction):
        # Use buffer for online solving
        self._last_solved.append(prediction)
        self._last_val.append(prediction)

        if len(self._last_solved) > self.kernel_size:
            # Case full buffer
            self._last_solved.pop(0)
            self._last_val.pop(0)

        if len(self._last_solved) <= 1:
            # Case single value in buffer
            # No solving strategie possible - use random label of set
            self._last_solved[-1] = random.choice(np.nonzero(prediction)[0])
            return self._last_solved[-1]

        else:
            self._last_solved[-1] = self.__run_solver_algo(self._last_val)

        if self._last_solved[-1] != -1:
            # Case accepted solved label
            self._last_solved_accepted.append([self._last_solved[-1], time.time()])
            if len(self._last_solved_accepted) > self.buffer_size_accepted_labels:
                self._last_solved_accepted.pop(0)
            return self._last_solved[-1]

        elif len(self._last_solved_accepted) > 0:
            # Case label not solvable (too many rejected sets)
            if (
                time.time() - self._last_solved_accepted[-1][1]
                > self.buffer_time_till_timeout
            ):
                raise TimeoutError("Last predicted samples to old, Consider retraining")
            return int(stats.mode(self._last_solved_accepted).mode[0])

        else:
            # Case no Label no buffer
            print("Unable to solve - no certain label, no buffer")
            return -1

    def __offline_solver(self, prediction):
        filtered_predictions = np.zeros(len(prediction), dtype=np.int16)
        for i in range(len(prediction)):
            if i < 1:
                filtered_predictions[i] = random.choice(np.nonzero(prediction[i])[0])
                continue
            if 1 <= i <= self.kernel_size:
                pred_block = prediction[: i + 1]
            else:
                pred_block = prediction[i - self.kernel_size : i + 1]

            filtered_predictions[i] = self.__run_solver_algo(pred_block)

            if filtered_predictions[i] != -1:
                # Case accepted solved label
                self._last_solved_accepted.append([self._last_solved[-1], time.time()])
                if len(self._last_solved_accepted) > self.buffer_size_accepted_labels:
                    self._last_solved_accepted.pop(0)

            elif len(self._last_solved_accepted) > 0:
                # Case label not solvable (too many rejected sets)
                if (
                    time.time() - self._last_solved_accepted[-1][1]
                    > self.buffer_time_till_timeout
                ):
                    raise TimeoutError(
                        "Last predicted samples to old, Consider retraining"
                    )
                filtered_predictions[i] = int(
                    stats.mode(self._last_solved_accepted).mode[0]
                )

            else:
                # Case no Label no buffer vreturn -1 as predictions
                print("Unable to solve - no certain label, no buffer")
                filtered_predictions[i] = filtered_predictions[i] - 1

        return filtered_predictions

    def __run_solver_algo(self, prediction):
        # TODO: CLEANUP
        prediction = np.array(prediction)

        # Case single estiamte - no prediction set
        if self.filter_single_sets == False and len(np.nonzero(prediction[-1])[0]) == 1:
            return np.argmax(prediction[-1])

        # Case empty prediction sets
        if np.sum(prediction) == 0:
            return -1

        if self.solver_strategie == "mode":
            # Case set greater one
            # TODO: how to do with 2 identical scores eg mode = 1 & 3
            classes = np.nonzero(prediction)
            return int(stats.mode(classes[1]).mode)

        elif self.solver_strategie == "weighted_mode":
            # TODO: Idea -> different weighting regarding set sizes
            # TODO: implement user based relevance_mask
            relevance_mask = np.geomspace(0.05, 1, len(prediction))[:, np.newaxis]
            weighted_classes = prediction * relevance_mask
            weighted_mode = np.argmax(np.sum(weighted_classes, axis=0))
            return int(weighted_mode)

        elif self.solver_strategie == "set_weighting":
            weights = np.maximum(
                np.sum(prediction, axis=-1), 1
            )  # avoid devision by zero on empty sets
            relevance_mask = np.linspace(0.3, 1, len(prediction))[:, np.newaxis]
            weights[-1] = 1  # Set weighting for current samples to 1

            weighted_classes = prediction * relevance_mask / weights[:, np.newaxis]
            weighted_mode = np.argmax(np.sum(weighted_classes, axis=0))
            return int(weighted_mode)
        elif self.solver_strategie == "set_weighting_v2":
            # TODO: ignore large sets
            # TODO: single prediction as close trigger
            # TODO: two single predictions as as open trigger
            return int(weighted_mode)
        else:
            raise NotImplementedError(f"Invalid solver mode: {self.solver_strategie}")


def smx_score_solver(prediction, smx_score, kernel_size):
    # TODO: implement threshold
    # TODO: implement relevance mask
    # TODO: implement threshold

    smx_arr = np.vstack(smx_score)
    pred_mask = prediction.astype(bool)
    scores_predictions = np.zeros_like(smx_score)
    scores_predictions[pred_mask] = smx_score[pred_mask]
    filtered_predictions = np.zeros_like(smx_arr[0])

    for i in range(kernel_size, len(prediction)):
        if len(np.nonzero(scores_predictions[i])[0]) != 1:
            # if (max(scores_predictions[i-1])<0.75):# TODO: check if makes sense maybe weight depending on set size
            weighted_predictions = scores_predictions[
                i - kernel_size : i
            ]  # *relevance_mask # maybe devide by numbers
            cummulativ_predictions = np.sum(weighted_predictions, axis=0)
            filtered_predictions[i] = np.argmax(cummulativ_predictions)
        else:
            filtered_predictions[i] = np.argmax(scores_predictions[i])

    return filtered_predictions
